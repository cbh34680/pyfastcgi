import os
import pathlib
import contextlib
import io
import http.client

'''
C:\devwork\workspaces\pyfastcgi\root\src>certutil -hashfile ..\data\KEN_ALL-utf8.CSV MD5
MD5 ハッシュ (対象 ..\data\KEN_ALL-utf8.CSV):
1d5858fcd7203064c8e931ec6f01fcfe
CertUtil: -hashfile コマンドは正常に完了しました。
'''

'''
C:\devwork\workspaces\pyfastcgi\root\src>curl 127.0.0.1/app/md5 --data-binary @..\data\KEN_ALL-utf8.CSV -H "Host: local" -H "Content-type: text/plain" --header "Transfer-Encoding: chunked"
1d5858fcd7203064c8e931ec6f01fcfe
'''

'''
C:\devwork\workspaces\pyfastcgi\root\src>python hash-client.py
200 OK
b'1d5858fcd7203064c8e931ec6f01fcfe'
'''

def main(conn:http.client.HTTPConnection, rfile:io.BufferedReader):
    buff = bytearray(4096)

    conn.putrequest('POST', '/app/hash')
    conn.putheader('Content-Type', 'text/plain')
    conn.putheader('Transfer-Encoding', 'chunked')
    conn.endheaders()

    while True:
        nread = rfile.readinto(buff)
        if not nread:
            break

        chunk_size = f'{nread:x}\r\n'.encode('utf-8')
        conn.send(chunk_size)

        with memoryview(buff) as mem:
            conn.send(mem[:nread])

        conn.send(b'\r\n')

    conn.send(b'0\r\n\r\n')

    resp = conn.getresponse()
    body = resp.read()
    print(resp.status, resp.reason)
    print(body)


if __name__ == '__main__':
    rpath = pathlib.Path(os.getcwd()) / '..' / 'data' / 'KEN_ALL-utf8.CSV'

    with(
        contextlib.closing(http.client.HTTPConnection('127.0.0.1', 80, timeout=5)) as conn,
        rpath.open('rb') as rfile,
    ):
        main(conn, rfile)

# EOF
