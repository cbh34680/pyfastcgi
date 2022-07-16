import os
import sys
import argparse
import collections
import dataclasses
import distutils.util
import enum
import pathlib
import socket
import tempfile
import threading
import traceback
import types
import pyfastcgi.protocol as protocol
from dataclasses import dataclass


CONST_STATUS = 'STatus'
CONST_CONTENT_TYPE = 'Content-Type'
CONST_CONTENT_LENGTH = 'Content-Length'
CONST_TRANSFER_ENCODING = 'Transfer-Encoding'


class StdioType(enum.Enum):
    NONE = 0
    MEMORY = 1
    STRING = 2
    TMPFILE = 3
    PATH = 4
    RESPONSE = 5

def stdio_type(strm) -> StdioType:
    if strm is None:
        return StdioType.NONE

    tstrm = type(strm)
    if tstrm in (bytes, bytearray):
        return StdioType.MEMORY

    if tstrm == str:
        return StdioType.STRING

    if isinstance(strm, tempfile._TemporaryFileWrapper):
        return StdioType.TMPFILE

    if isinstance(strm, pathlib.Path):
        return StdioType.PATH

    if isinstance(strm, Response):
        return StdioType.RESPONSE

    assert False, f'un-expected type: {tstrm=}'


@dataclass(frozen=True)
class Event:
    name:str
    data:any = None

@dataclass
class Context:
    pid:int
    _stats:collections.Mapping
    _stats_lock:any
    _handler:callable
    responder_factory:callable
    bind_addr:any
    pid_path:str
    temp_dir:str
    threads:int
    nonblocking:bool
    max_stdio_mem:int
    so_timeout:float
    extra:collections.Mapping
    loop:bool = dataclasses.field(init=False, default=True)

    def handler(self, event:Event):
        if self._handler:
            self._handler(self, event)

    @property
    def stats(self):
        with self._stats_lock:
            a = self._stats.copy()

        return a

    def incr_stats(self, *keys):
        keys = set(keys)

        with self._stats_lock:
            for key in keys:
                self._stats.setdefault(key, 0)
                self._stats[key] += 1

    def get_stats(self, key:str) -> int:
        with self._stats_lock:
            a = self._stats[key]

        return a

@dataclass(frozen=True)
class Response:
    headers:collections.Mapping
    body:any = None

    def getKey(self, arg:str):
        if arg in self.headers:
            return arg

        arg = arg.strip().lower()
        for k, _ in self.headers.items():
            if k.strip().lower() == arg:
                return k

        return None

    def getContentLengthKey(self):
        return self.getKey(CONST_CONTENT_LENGTH)

    def hasContentLength(self) -> bool:
        return False if self.getContentLengthKey() is None else True

    def getTransferEncodinghKey(self):
        return self.getKey(CONST_TRANSFER_ENCODING)

    def hasTransferEncoding(self) -> bool:
        return False if self.getTransferEncodinghKey() is None else True

    def deleteHeaderItem(self, key:str):
        key = self.getKey(key)
        if key is None:
            return False

        del self.headers[key]
        return True

    @property
    def chunked(self):
        return False

    def dumpHeaders(self) -> bytes:
        h = self.headers.copy()

        if self.chunked:
            if not self.hasTransferEncoding():
                h[CONST_TRANSFER_ENCODING] = 'chunked'

            deleted = self.deleteHeaderItem(CONST_CONTENT_LENGTH)
            if deleted:
                print(f'header-key({CONST_CONTENT_LENGTH}) is ignore', file=sys.stderr)

        else:
            if not self.hasContentLength():
                h[CONST_CONTENT_LENGTH] = self.getBodyLength()

            deleted = self.deleteHeaderItem(CONST_TRANSFER_ENCODING)
            if deleted:
                print(f'header-key({CONST_TRANSFER_ENCODING}) is ignore', file=sys.stderr)

        h = '\r\n'.join([ f'{k.strip()}: {str(v).strip()}' for k,v in h.items() ])
        h = h.encode('ascii')
        ret = h + b'\r\n\r\n'

        return ret

    def getBodyLength(self) -> int:
        tbody = stdio_type(self.body)

        if tbody == StdioType.NONE:
            clen = 0

        elif tbody in (StdioType.MEMORY, StdioType.STRING):
            clen = len(self.body)

        elif tbody == StdioType.PATH:
            clen = self.body.stat().st_size

        elif tbody == StdioType.TMPFILE:
            clen = os.stat(self.body.name).st_size

        else:
            assert False

        return clen

    def dump(self) -> bytes:
        h = self.dumpHeaders()
        ret = h + self.body if not self.body is None else h

        return ret

class ChunkedResponse(Response):
    @property
    def chunked(self):
        return True

@dataclass(frozen=True)
class _BaseResponder:
    context:Context
    conn:socket.socket
    client:tuple
    requestId:int
    params:collections.Mapping

    def do_response(self):
        ...

    def close(self):
        ...


def report_exception(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)

        except Exception as e:
            traceback.print_exception(*sys.exc_info(), file=sys.stderr)
            raise

    return wrapper


def test_response():
    a = Response({'Content-Length': 100})
    if a.hasContentLength():
        print('1:' + a.getContentLengthKey() + ';')

    a = Response({'content-length': 100})
    if a.hasContentLength():
        print('2:' + a.getContentLengthKey() + ';')

    a = Response({'   content-length   ': 100})
    if a.hasContentLength():
        print('3:' + a.getContentLengthKey() + ';')

    a = Response({'   c0ntent-length   ': 100})
    if a.hasContentLength():
        print('4:' + a.getContentLengthKey() + ';')

    a = Response({'   content-length   ': 100, '  transfer-encoding  ': 'chunked'})
    if a.hasTransferEncoding():
        print('5:' + a.getTransferEncodinghKey() + ';')

    a.deleteHeaderItem('  content-length  ')
    if a.hasContentLength():
        print('6:' + a.getContentLengthKey() + ';')


def parse_args():
    #test_response()
    parser = argparse.ArgumentParser()

    parser.add_argument('--chdir', dest='workdir', help='change work-directory')
    parser.add_argument('--pid-path', dest='pid_path', help='pid save full-path')
    parser.add_argument('--temp-dir', dest='temp_dir', default=tempfile.gettempdir(), help='temporary directory')
    parser.add_argument('--addr', dest='bind_addr', default='', help='bind tcp/ip address')
    parser.add_argument('--port', dest='bind_port', type=int, default=9000, help='bind tcp/ip port-number')
    parser.add_argument('--file', dest='bind_file', help='bind unix-domain-socket')
    parser.add_argument('--threads', dest='threads', type=int, default=1, help='number of threads')
    parser.add_argument('--non-blocking', dest='nonblocking', type=distutils.util.strtobool, default=0, help='use non-blocking select')
    parser.add_argument('--max-stdio-mem', dest='max_stdio_mem', type=int, default=sys.maxsize, help='max size of stdin in memory')
    parser.add_argument('--so-timeout', dest='so_timeout', type=float, default=3.0, help='socket timeout')

    cmdargs, _ = parser.parse_known_args()

    if not cmdargs.workdir is None:
        os.chdir(cmdargs.workdir)

    if not cmdargs.pid_path is None:
        # https://qiita.com/pytry3g/items/aa38d8c2acf59b90aaac
        #print(f'{os.getpid()}', file=open(cmdargs.pid_path, 'w'), end='', flush=True)

        with open(cmdargs.pid_path, 'w') as f:
            f.write(f'{os.getpid()}')

    bind_addr = cmdargs.bind_file if cmdargs.bind_file else (cmdargs.bind_addr, cmdargs.bind_port)

    a = {
        'bind_addr':     bind_addr,
        'pid_path':      cmdargs.pid_path,
        'temp_dir':      cmdargs.temp_dir,
        'threads':       cmdargs.threads,
        'nonblocking':   cmdargs.nonblocking != 0,
        'max_stdio_mem': cmdargs.max_stdio_mem,
        'so_timeout':    cmdargs.so_timeout,
        'extra':         {},
    }

    return a


def make_context(config:collections.Mapping, *, event_handler:callable=None, responder_factory=None):
    a = (
        os.getpid(),
        {},                      # _stats
        threading.Lock(),        # _stats_lock
        event_handler,
        responder_factory,
        config['bind_addr'],
        config['pid_path'],
        config['temp_dir'],
        config['threads'],
        config['nonblocking'],
        config['max_stdio_mem'],
        config['so_timeout'],
        types.MappingProxyType(config['extra']),
    )

    return Context(*a)


def send_record(conn:socket.socket, recordType:int, requestId:int, *, contentData=b'', contentLength=-1) -> int:
    cdtype = stdio_type(contentData)

    if cdtype == StdioType.MEMORY:
        return protocol.send_record(conn, recordType, requestId, contentData=contentData, contentLength=contentLength)

    else:
        if cdtype == StdioType.STRING:
            return send_record(conn, recordType, requestId, contentData=contentData.encode('utf-8'))

        elif cdtype == StdioType.RESPONSE:
            hresp:Response = contentData
            assert isinstance(hresp.headers, collections.Mapping)

            rbtype = stdio_type(hresp.body)

            if rbtype in (StdioType.NONE, StdioType.MEMORY):
                return send_record(conn, recordType, requestId, contentData=hresp.dump())

            elif rbtype == StdioType.STRING:
                newhresp = Response(hresp.headers, hresp.body.encode('utf-8'))
                return send_record(conn, recordType, requestId, contentData=newhresp.dump())

            elif rbtype == StdioType.TMPFILE:
                newhresp = Response(hresp.headers, pathlib.Path(hresp.body.name))
                return send_record(conn, recordType, requestId, contentData=newhresp)

            elif rbtype == StdioType.PATH:
                http_headers = hresp.dumpHeaders()       # b'Content-Type: text/plain\r\nContent...\r\n\r\n'
                sum_send = send_record(conn, recordType, requestId, contentData=http_headers)

                with hresp.body.open('rb') as f:
                    while True:
                        contentData = f.read(protocol.PACKET_IO_LEN)
                        if not len(contentData):
                            break

                        sum_send += send_record(conn, recordType, requestId, contentData=contentData)

                return sum_send
            else:
                assert False
        else:
            assert False
    assert False

    # end-if

# EOF
