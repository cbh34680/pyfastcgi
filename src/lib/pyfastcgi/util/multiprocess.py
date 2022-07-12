import os
import sys
import argparse
import atexit
import functools
import platform
import time
import signal
import socket
import importlib.util
import collections
import pyfastcgi


def unlink_pid_file(pid_path):
    if os.path.exists(pid_path):
        print(f'unlink {pid_path=}', file=sys.stderr)
        os.unlink(pid_path)


def signal_hanlder(context:pyfastcgi.Context, signum, frame):
    print(f'{os.getpid()=} catch signal {signum=}, set loop=OFF', file=sys.stderr)

    context.loop = False
    signal.signal(signum, signal.SIG_DFL)


def gen_subprocess(context:pyfastcgi.Context):
    reg_unlink = False
    childs = set()
    procs = context.extra['procs']

    while context.loop:
        nfork = procs - len(childs)

        for _ in range(nfork):
            pid = os.fork()

            if pid == 0:
                # is child
                return

            # is parent
            print(f'create new-process {pid=}', file=sys.stderr)
            childs.add(pid)

        else:
            # parent
            if not reg_unlink:
                # regist once
                reg_unlink = True

                if context.pid_path:
                    atexit.register(unlink_pid_file, context.pid_path)

            while context.loop:
                # check alive
                exit_pid, exit_rc = os.waitpid(-1, os.WNOHANG)

                if exit_pid:
                    print(f'sub-process dead {exit_pid=} {exit_rc // 256}', file=sys.stderr)
                    childs.remove(exit_pid)
                    # return big-loop and create sub-process
                    break

                #print('wait...')
                time.sleep(1)

            else:
                do_finalize(context, childs)

    # end while (bit-loop)

    print('all done.', file=sys.stderr)
    exit(0)


def do_finalize(context:pyfastcgi.Context, childs:set):
    print('* detected terminate, start finalize', file=sys.stderr)
    SLEEP_SEC = context.so_timeout / 2

    # first SIGTERM
    print('* send SIGTERM to sub-processes', file=sys.stderr)
    send_signal(signal.SIGTERM, childs)

    print(f'wait {SLEEP_SEC} sec for receive signal...', file=sys.stderr)
    time.sleep(SLEEP_SEC)
    print(f'wake up', file=sys.stderr)

    update_childs(childs, SLEEP_SEC)

    if not context.nonblocking:

        print('* send NULL to sub-processes', file=sys.stderr)

        send_last_packet(context.bind_addr, len(childs))

        print(f'wait {SLEEP_SEC} sec for terminate process...', file=sys.stderr)
        time.sleep(SLEEP_SEC)
        print(f'wake up', file=sys.stderr)

        update_childs(childs, SLEEP_SEC)

    if childs:
        print('* force kill sub-processes', file=sys.stderr)

        # second SIGKILL
        send_signal(signal.SIGKILL, childs)

        print(f'wait {SLEEP_SEC} sec for receive signal...', file=sys.stderr)
        time.sleep(SLEEP_SEC)
        print(f'wake up', file=sys.stderr)

        update_childs(childs, SLEEP_SEC)

    else:
        print('* detect all sub-processes exited', file=sys.stderr)

    print('* end finalize', file=sys.stderr)


def send_last_packet(bind_addr, nchilds:int):
    if type(bind_addr) == str:
        family = socket.AF_UNIX
        conn_addr = bind_addr

    else:
        family = socket.AF_INET
        conn_addr = (socket.gethostname(), bind_addr[1])

    for i in range(nchilds):
        print(f'send null packet {i+1}/{nchilds}', file=sys.stderr)

        conn = socket.socket(family, socket.SOCK_STREAM)
        conn.connect(conn_addr)
        conn.sendall(b'\x00')
        conn.close()


def send_signal(signum:int, childs:set):
    for child_pid in childs:
        print(f'send {signum=} to {child_pid=}', file=sys.stderr)
        os.kill(child_pid, signum)


def update_childs(childs:set, sleep_sec:float):
    RETRY = 5
    print(f'check alive {RETRY} times', file=sys.stderr)

    for i in range(RETRY):
        time.sleep(sleep_sec)

        print(f'check sub-process is alive {i+1}/{RETRY}', file=sys.stderr)

        nchilds = len(childs)
        if not childs:
            print('no more sub-process', file=sys.stderr)
            break

        for j in range(nchilds):
            print(f'check sub-process {j+1}/{nchilds}', file=sys.stderr)
            exit_pid, exit_rc = os.waitpid(-1, os.WNOHANG)

            if exit_pid:
                childs.remove(exit_pid)
                print(f'detected terminate of {exit_pid=} {exit_rc=}', file=sys.stderr)
    else:
        print(f'give up !!', file=sys.stderr)


def event_handler_hook(orig_handler:callable, context:pyfastcgi.Context, event:pyfastcgi.Event):
    orig_handler(context, event)

    if event.name == 'ACCEPT':
        accepted = context.get_stats('socket-accepted')
        max_request = context.extra['max_request']

        if accepted > max_request:
            print('accept exceeded max-request', file=sys.stderr)
            context.loop = False

    elif event.name == 'LISTEN':
        gen_subprocess(context)

    elif event.name == 'STOP-LISTENER':
        pid = os.getpid()

        if context.pid != pid:
            print(f'subprocess exit pid={pid}', file=sys.stderr)
            os._exit(0)


def make_context(config:collections.Mapping):

    parser = argparse.ArgumentParser()
    parser.add_argument('--app-path', dest='app_path', default='app.py', help='load application full-path')
    parser.add_argument('--event-handler', dest='event_handler', default='event_handler', help='event_handler func name in app')
    parser.add_argument('--responder', dest='responder_factory', default='Responder', help='responder class name in app')
    parser.add_argument('--procs', dest='procs', type=int, default=1, help='number of processes')
    parser.add_argument('--max-request', dest='max_request', type=int, default=sys.maxsize, help='request-limit per process')
    cmdargs, _ = parser.parse_known_args()

    config['extra']['procs'] = cmdargs.procs
    config['extra']['max_request'] = cmdargs.max_request

    # https://www.delftstack.com/ja/howto/python/import-python-file-from-path/

    app_name = os.path.splitext(os.path.basename(cmdargs.app_path))[0]
    spec = importlib.util.spec_from_file_location(app_name, cmdargs.app_path)
    app_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app_mod)

    has_fork = platform.system() in ('Linux', 'Darwin', )

    orig_handler = getattr(app_mod, cmdargs.event_handler)
    ev_handler = functools.partial(event_handler_hook, orig_handler) if has_fork else orig_handler

    responder_factory = getattr(app_mod, cmdargs.responder_factory)

    context = pyfastcgi.make_context(config, event_handler=ev_handler, responder_factory=responder_factory)
    print(f'{context=}', file=sys.stderr)

    '''
    https://linuxjm.osdn.jp/html/LDP_man-pages/man7/signal.7.html
    fork(2) 経由で作成された子プロセスは、親プロセスのシグナルの処理方法の コピーを継承する。
    '''
    sig_handler = functools.partial(signal_hanlder, context)
    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGINT, sig_handler)

    return context


def main():
    config = pyfastcgi.parse_args()
    context = make_context(config)
    pyfastcgi.start_listener(context)


if __name__ == '__main__':
    main()

# EOF
