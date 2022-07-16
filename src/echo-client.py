import os
import sys
import pathlib
import contextlib
import socket
import selectors
import io
import dataclasses
from dataclasses import dataclass


BUFFER_LEN = 4096
SEND_BUFFER_LEN = BUFFER_LEN
RECV_BUFFER_LEN = BUFFER_LEN


@dataclass
class SessionData:
    rfile:io.BufferedReader
    wfile:io.BufferedWriter
    sendbuf:bytearray
    recvbuf:bytearray
    sendbuf_len:int = dataclasses.field(init=False, default=0)
    sendbuf_pos:int = dataclasses.field(init=False, default=0)
    sum_read:int = dataclasses.field(init=False, default=0)
    sum_send:int = dataclasses.field(init=False, default=0)
    sum_recv:int = dataclasses.field(init=False, default=0)
    loop:bool = dataclasses.field(init=False, default=True)

@dataclass
class RegistData:
    callback:callable
    session:SessionData


def on_read(conn:socket.socket, selector:selectors.SelectSelector, session:SessionData):
    nrecv = conn.recv_into(session.recvbuf)

    if nrecv == 0:
        selector.unregister(conn)
        conn.shutdown(socket.SHUT_RDWR)
        conn.close()

        session.loop = False
        return

    session.sum_recv += nrecv

    print(f'recv {nrecv=}', file=sys.stderr)

    with memoryview(session.recvbuf) as recvbuf:
        session.wfile.write(recvbuf[:nrecv])


def on_write(conn:socket.socket, selector:selectors.SelectSelector, session:SessionData):
    if session.sendbuf_pos == 0:
        with memoryview(session.sendbuf) as sendbuf:
            '''
            8 = "0000000f" (chunk body len)
            2 = "\r\n"
            '''
            assert len(sendbuf) <= 1024 * 1024 * 1024 - 8 - 2 - 2

            nread = session.rfile.readinto(sendbuf[8 + 2:-2])
            if nread == 0:

                conn.sendall(b'0\r\n\r\n')
                conn.shutdown(socket.SHUT_WR)

                key = selector.get_key(conn)
                selector.modify(conn, selectors.EVENT_READ, key.data)

                return

            session.sum_read += nread

            termpos = 8 + 2 + nread
            session.sendbuf_len = termpos + 2

            sendbuf[termpos:session.sendbuf_len] = b'\r\n'                       # ".........\r\n"

            chunk_body_len = f'{nread:08x}'.encode('utf-8')
            nchunk_body_len = len(chunk_body_len)

            sendbuf[:nchunk_body_len] = chunk_body_len                 # "0000000f....."
            sendbuf[nchunk_body_len:nchunk_body_len+2] = b'\r\n'       # "0000000f\r\n..."

    #print(f'{session.sendbuf=}')

    with memoryview(session.sendbuf) as snfbuf:
        nsend = conn.send(snfbuf[session.sendbuf_pos:session.sendbuf_len])

        print(f'send {nsend=}', file=sys.stderr)

        session.sum_send += nsend
        session.sendbuf_pos += nsend

        if session.sendbuf_pos == session.sendbuf_len:
            session.sendbuf_len = 0
            session.sendbuf_pos = 0


def on_event(conn:socket.socket, selector:selectors.SelectSelector, session:SessionData, mask):
    if mask & selectors.EVENT_READ:
        on_read(conn, selector, session)

    if mask & selectors.EVENT_WRITE:
        on_write(conn, selector, session)


def main(conn:socket.socket, selector:dict, rfile, wfile):
    headers = (
        'POST /app/post HTTP/1.1',
        'Host: localhost',
        'Content-Type: text/plain; charset=utf-8',
        'Transfer-Encoding: chunked',
    )
    headers = '\r\n'.join(headers).encode('utf-8') + b'\r\n\r\n'

    session = SessionData(rfile, wfile, bytearray(SEND_BUFFER_LEN), bytearray(RECV_BUFFER_LEN))

    conn.connect((socket.gethostname(), 80))
    conn.sendall(headers)
    print(f'{headers=}')

    conn.setblocking(False)
    selector.register(conn, selectors.EVENT_READ | selectors.EVENT_WRITE, RegistData(on_event, session))

    while session.loop:
        try:
            readies = selector.select()
            if readies:
                for key, mask in readies:
                    key.data.callback(conn, selector, key.data.session, mask)
            else:
                print(f'timeout')

        except Exception as e:
            print(f'{e}')

    print(f'{session.sum_read=} {session.sum_send=} {session.sum_recv=}')

    print('done.')

if __name__ == '__main__':
    rpath = pathlib.Path(os.getcwd()) / '..' / 'data' / 'KEN_ALL-utf8.CSV'
    wpath = pathlib.Path(os.getcwd()) / 'response.txt'

    with(
        contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as conn,
        selectors.DefaultSelector() as selector,
        rpath.open('rb') as rfile,
        wpath.open('wb') as wfile,
    ):
        main(conn, selector, rfile, wfile)

# EOF
