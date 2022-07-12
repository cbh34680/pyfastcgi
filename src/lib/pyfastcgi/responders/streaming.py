import collections
import contextlib
import dataclasses
import socket
import pyfastcgi
import pyfastcgi.protocol as protocol
import pyfastcgi.responders.errors as errors
from contextlib import contextmanager
from dataclasses import dataclass


_CHUNK_PREFIX = b'****\r\n'
_CHUNK_SUFFIX = b'\r\n'
_CHUNK_END = b'0\r\n\r\n'


class StreamingResponder(pyfastcgi._BaseResponder):
    stdin_read = False
    _stdout_sent = False

    @property
    def stdout_sent(self):
        return self._stdout_sent

    def do_response(self):
        try:
            self.on_request()

        except (ConnectionError, errors.ResponseError):
            raise

        except Exception as e:
            if self.stdout_sent:
                '''
                既に open_stdout() が実行されていたらエラーのレスポンスは送信不要
                --> UnnecessaryResponseError を派生した ResponsingError を送出する
                '''
                raise errors.ResponsingError() from e
            raise

    def on_request(self):
        ...

    def _each_stdin_record(self):
        if self.stdin_read:
            cause = errors.NoMoreStreamDataError()

            if self.stdout_sent:
                raise errors.HeaderAlreadySentError() from cause
            raise cause

        self.stdin_read = True

        while True:
            record = protocol.read_record(self.conn)
            assert record.header.requestId == self.requestId
            assert record.header.recordType == protocol.FCGI_STDIN

            if record.header.contentLength == 0:
                break

            yield record

    def each_stdin(self):
        #for record in self.each_stdin_record():
        #    yield record.contentData

        # https://blanktar.jp/blog/2015/07/python-yield-from

        yield from map(lambda record: record.contentData, self._each_stdin_record())

    @contextmanager
    def open_stdout(self, headers:collections.Mapping):
        if self.stdout_sent:
            raise errors.HeaderAlreadySentError()

        self._stdout_sent = True

        '''
        Content-Length がわからない状態での送信なので "Transfer-Encoding: chunked" を
        強制したヘッダのみ最初に送信する
        '''
        chunked_response = pyfastcgi.ChunkedResponse(headers)
        chunked_header = chunked_response.dumpHeaders()
        pyfastcgi.send_record(self.conn, protocol.FCGI_STDOUT, self.requestId, contentData=chunked_header)

        # chunk 形式の送信を行うストリームを返却
        with contextlib.closing(_ChunkedTransferStream(self.conn, self.requestId)) as stream:
            yield stream


@dataclass
class _ChunkedTransferStream:
    conn:socket.socket
    requestId:int
    closed:bool = dataclasses.field(init=False, default=False)
    sndbuf:bytearray = dataclasses.field(init=False, default=None)
    sndbuf_pos:int = dataclasses.field(init=False, default=-1)

    def send_record_stdout(self, contentData=b'', contentLength=-1):
        '''
        a = os.path.join(os.path.dirname(__file__), 'chunked-data.txt')
        with open(a, 'ab') as f:
            if contentLength < 0:
                f.write(contentData)

            else:
                f.write(contentData[0:contentLength])
        '''

        return pyfastcgi.send_record(self.conn, protocol.FCGI_STDOUT, self.requestId, contentData=contentData, contentLength=contentLength)

    def write(self, data=b''):
        if self.closed:
            return -1

        if self.sndbuf is None:
            self.sndbuf = bytearray(protocol.PACKET_IO_CONTENT_LEN)
            self.sndbuf_pos = len(_CHUNK_PREFIX)

            '''
            {sndbuf} は固定サイズで以下のフォーマットになる

            1) データが最大サイズまで設定されている場合
                "1ff0\r\n" + bytes(8176) + "\r\n" ... 8184 byte

            2) [1)] 以外の場合 (データ 300 byte)
                "012c\r\n" + bytes(300) + "\r\n"  ...  308 byte

            * 最大サイズの 8176 は以下の考えにより
                8192 - 8 (sizeof(FCGI_RecordHeader)) - 8 (余裕) = 8176
            '''
            self.sndbuf[:len(_CHUNK_PREFIX)]  = _CHUNK_PREFIX
            self.sndbuf[-len(_CHUNK_SUFFIX):] = _CHUNK_SUFFIX

        tdata = type(data)
        if tdata == str:
            data = data.encode('utf-8')

        ndata = len(data)
        if ndata == 0:
            # '0\r\n' を送信するとそれ以降を受信しなくなるため無視
            return -1

        sum_send = 0

        nsndbuf = len(self.sndbuf) - len(_CHUNK_SUFFIX)
        sndbuf_remaining = nsndbuf - self.sndbuf_pos

        with memoryview(data) as mem:
            nmem = len(mem)
            mem_pos = 0
            mem_remaining = nmem - mem_pos

            while mem_remaining:
                assert mem_remaining > 0

                # memncpy(&sndbuf[sndbuf_pos], &data[mem_pos], advance)
                advance = mem_remaining if mem_remaining <= sndbuf_remaining else sndbuf_remaining
                self.sndbuf[self.sndbuf_pos:self.sndbuf_pos+advance] = mem[mem_pos:mem_pos+advance]

                # point next-position
                self.sndbuf_pos += advance
                mem_pos += advance

                # update remaining
                sndbuf_remaining = nsndbuf - self.sndbuf_pos
                mem_remaining = nmem - mem_pos

                assert sndbuf_remaining >= 0
                assert mem_remaining >= 0

                if sndbuf_remaining == 0:
                    '''
                    no more space
                    '''
                    # set chunk-size (0000 - ffff)
                    nchunk_content = len(self.sndbuf) - len(_CHUNK_PREFIX) - len(_CHUNK_SUFFIX)
                    nchunk_content_04x = f'{nchunk_content:04x}'.encode('utf-8')
                    self.sndbuf[:len(nchunk_content_04x)] = nchunk_content_04x

                    # send all {sndbuf}
                    nsend = self.send_record_stdout(self.sndbuf)
                    sum_send += nsend

                    # reset {sndbuf}
                    self.sndbuf_pos = len(_CHUNK_PREFIX)
                    sndbuf_remaining = nsndbuf - self.sndbuf_pos

        return sum_send

    def close(self):
        if self.closed:
            raise errors.StreamAlreadyClosedError()

        self.closed = True

        if self.sndbuf is None:
            # 一度も write() が実行されなかったとき = POST の length==0
            pass

        else:
            assert self.sndbuf_pos >= 0

            if not self.sndbuf_pos == len(_CHUNK_PREFIX):
                '''
                flush buffer
                '''
                # set chunk-size (0000 - ffff)
                a = self.sndbuf_pos - len(_CHUNK_PREFIX)
                chunk_len = f'{a:04x}'.encode('utf-8')
                self.sndbuf[:len(chunk_len)] = chunk_len

                # get effective data
                effective = self.sndbuf_pos + len(_CHUNK_SUFFIX)

                # set terminator
                self.sndbuf[self.sndbuf_pos:effective] = b'\r\n'

                # send {sndbuf}[0:effective]
                self.send_record_stdout(self.sndbuf, effective)

        # terminate chunk
        self.send_record_stdout(_CHUNK_END)

        # terminate stdout
        self.send_record_stdout()

    def __del__(self):
        if not self.closed:
            self.close()

# EOF
