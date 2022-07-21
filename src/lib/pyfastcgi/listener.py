import os
import sys
import atexit
import concurrent.futures
import contextlib
import functools
import http.client
import selectors
import socket
import struct
import traceback
import uuid
import pyfastcgi
import pyfastcgi.protocol as protocol
import pyfastcgi.responders
import pyfastcgi.responders.errors as errors


def send_fatal_error(conn:socket.socket, requestId:int, errmsg:str, exinfo:tuple, http_code:int=http.client.INTERNAL_SERVER_ERROR):
    try:
        http_mesg = http.client.responses[http_code]

        headers = {
            pyfastcgi.CONST_STATUS: f'{http_code} {http_mesg}',
            pyfastcgi.CONST_CONTENT_TYPE: 'text/html; charset=utf-8',
        }

        errcode = str(uuid.uuid4())
        textmsg = f'error-code={errcode}'
        htmlmsg = f'<html><body>{textmsg}</body></html>'
        hresp = pyfastcgi.Response(headers, htmlmsg)

        pyfastcgi.send_record(conn, protocol.FCGI_STDOUT, requestId, contentData=hresp)
        pyfastcgi.send_record(conn, protocol.FCGI_STDOUT, requestId)

        a = traceback.format_exception(*exinfo)
        logmsg = f'{textmsg}; {errmsg}; ' + '; '.join(( v.replace('\n', '').strip() for v in a ))

        pyfastcgi.send_record(conn, protocol.FCGI_STDERR, requestId, contentData=logmsg)
        pyfastcgi.send_record(conn, protocol.FCGI_STDERR, requestId)

    except:
        # ignore
        pass


@pyfastcgi.report_exception
def process_request(context:pyfastcgi.Context, conn:socket.socket, client:tuple):
    conn.settimeout(context.so_timeout)

    keep_conn = True
    while keep_conn:
        record = protocol.read_record(conn)

        if record.header.recordType != protocol.FCGI_BEGIN_REQUEST:
            continue

        requestId = record.header.requestId
        appStatus = 0

        try:
            try:
                a = struct.unpack('>HB5s', record.contentData)
                begreq = protocol.FCGI_BeginRequestBody(*a)

                keep_conn = begreq.flags & protocol.FCGI_KEEP_CONN
                if keep_conn:
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
                    print('enable keep connection', file=sys.stderr)
                    assert False, 'un-expected keep=enabled, tracking'

                params = {}

                while True:
                    record = protocol.read_record(conn)
                    assert record.header.requestId == requestId
                    assert record.header.recordType == protocol.FCGI_PARAMS

                    if record.header.contentLength == 0:
                        break

                    with memoryview(record.contentData) as mem:
                        a = protocol.make_params(mem)

                        # >=3.9
                        #params |= a

                        # <3.9
                        params.update(a)

                responder = None
                if context.responder_factory:
                    responder = context.responder_factory(context, conn, client, requestId, params)

                if not a:
                    responder = pyfastcgi.responders.NotImplementedResponder(context, conn, client, requestId, params)

                with contextlib.closing(responder):
                    appStatus = responder.do_response() or 0

                context.incr_stats('response-ok')

            except:
                context.incr_stats('response-ng')
                traceback.print_exception(*sys.exc_info(), file=sys.stderr)
                raise

        except ConnectionError:
            break

        except errors.UnnecessaryResponseError as e:
            appStatus = 241     # no mean value

        except Exception as e:
            exinfo = sys.exc_info()
            send_fatal_error(conn, requestId, str(e), exinfo)

            appStatus = 242     # no mean value

        # end
        endreq = protocol.FCGI_EndRequestBody(appStatus, protocol.FCGI_REQUEST_COMPLETE)
        pyfastcgi.send_record(conn, protocol.FCGI_END_REQUEST, requestId, contentData=endreq.dump())

    # end while True


def on_accepted(context:pyfastcgi.Context, conn:socket.socket, client:tuple):
    try:
        print(f'accepted {conn=}', file=sys.stderr)

        process_request(context, conn, client)

    finally:
        print(f'terminate {conn=}', file=sys.stderr)

        '''
        [FCGI_KEEP_CONN]
            ゼロの場合、アプリケーションはこの要求に応答した後に接続を閉じます。
            ゼロでない場合、アプリケーションはこの要求に応答した後、接続を閉じません。Webサーバーは接続の責任を保持します。
        '''
        if protocol.close_socket(conn):
            context.incr_stats('socket-closed')
            print(conn, file=sys.stderr)

        print(f'request done. from {client=}', file=sys.stderr)


def accept_submit(context:pyfastcgi.Context, executor:concurrent.futures.ThreadPoolExecutor, ssock:socket.socket):
    try:
        conn, address = ssock.accept()

        if context.loop:
            context.incr_stats('socket-accepted')

            ainfo = {
                'ssock': ssock,
                'executor': executor,
                'conn': conn,
            }
            context.handler(pyfastcgi.Event('ACCEPT', ainfo))
            executor.submit(on_accepted, context, conn, address)

    except BlockingIOError as e:
        context.incr_stats('socket-blockerr')
        print(f'{os.getpid()=} {str(e)}, ignore', file=sys.stderr)

    except socket.timeout as e:
        context.incr_stats('socket-timeout')
        context.handler(pyfastcgi.Event('IDLE'))


def nonblocking_loop(context:pyfastcgi.Context, ssock:socket.socket):
    with concurrent.futures.ThreadPoolExecutor(max_workers=context.threads) as executor, \
         selectors.DefaultSelector() as selector:
        '''
        https://docs.python.org/ja/3/library/socket.html#socket-timeouts

        sock.setblocking(True) は sock.settimeout(None) と等価です
        sock.setblocking(False) は sock.settimeout(0.0) と等価です
        '''
        ssock.setblocking(False)

        # https://docs.python.org/ja/3/library/selectors.html

        a = functools.partial(accept_submit, context, executor)
        selector.register(ssock, selectors.EVENT_READ, a)

        while context.loop:
            context.incr_stats('nonblocking-loop')
            readies = selector.select(context.so_timeout)

            if readies:
                for ready, _ in readies:
                    callback = ready.data
                    callback(ssock)

            else:
                context.incr_stats('select-timeout')
                context.handler(pyfastcgi.Event('IDLE'))


def blocking_loop(context:pyfastcgi.Context, ssock:socket.socket):
    with concurrent.futures.ThreadPoolExecutor(max_workers=context.threads) as executor, \
         selectors.DefaultSelector() as selector:

        ssock.settimeout(context.so_timeout)

        while context.loop:
            context.incr_stats('bloking-loop')
            accept_submit(context, executor, ssock)


def unlink_bind_file(bind_path:str):
    if os.path.exists(bind_path):
        print(f'unlink {bind_path=}', file=sys.stderr)
        os.unlink(bind_path)


@pyfastcgi.report_exception
def start(context:pyfastcgi.Context):
    context.handler(pyfastcgi.Event('START-LISTENER'))

    oldmask = None

    if type(context.bind_addr) == str:
        family = socket.AF_UNIX

        if os.path.exists(context.bind_addr):
            print(f'unlink {context.bind_addr=}', file=sys.stderr)
            os.unlink(context.bind_addr)

        oldmask = os.umask(0o111)

        atexit.register(unlink_bind_file, context.bind_addr)

    else:
        family = socket.AF_INET

    with socket.socket(family, socket.SOCK_STREAM) as ssock:
        ssock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ssock.bind(context.bind_addr)
        ssock.listen()

        if not oldmask is None:
            os.umask(oldmask)

        context.handler(pyfastcgi.Event('LISTEN'))

        if context.nonblocking:
            nonblocking_loop(context, ssock)

        else:
            blocking_loop(context, ssock)

    context.handler(pyfastcgi.Event('STOP-LISTENER'))

# EOF
