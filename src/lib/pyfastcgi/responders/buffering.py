import os
import sys
import mmap
import pathlib
import shutil
import tempfile
import pyfastcgi
import pyfastcgi.protocol as protocol
import pyfastcgi.responders.errors as errors
import pyfastcgi.responders.streaming as streaming
from contextlib import contextmanager


def _close_tempfile(tmpf):
    assert isinstance(tmpf, tempfile._TemporaryFileWrapper)

    if not tmpf.closed:
        tmpf.close()

    if os.path.exists(tmpf.name):
        print(f'unlink {tmpf.name=}', file=sys.stderr)
        os.unlink(tmpf.name)


class BufferingResponder(streaming.StreamingResponder):
    _stdin = None
    stdin_fixed_len = 0
    stdin_pos = 0

    def on_request(self):
        stdout_data = None

        try:
            stdout_data = self.make_response()

            if self.stdout_sent:
                '''
                既に親クラス(StreamingResponder) の open_stdout() を利用して chunked を送信済
                '''
                if not stdout_data is None:
                    raise errors.HeaderAlreadySentError()

            else:
                if stdout_data is None:
                    raise errors.NoResponseError()

                pyfastcgi.send_record(self.conn, protocol.FCGI_STDOUT, self.requestId, contentData=stdout_data)

        finally:
            if not stdout_data is None:
                if pyfastcgi.stdio_type(stdout_data) == pyfastcgi.StdioType.RESPONSE:
                    hresp:pyfastcgi.Response = stdout_data

                    if pyfastcgi.stdio_type(hresp.body) == pyfastcgi.StdioType.TMPFILE:
                        _close_tempfile(hresp.body)

    def close(self):
        if not self._stdin is None:
            if pyfastcgi.stdio_type(self._stdin) == pyfastcgi.StdioType.TMPFILE:
                _close_tempfile(self._stdin)

    def make_response(self):
        ...

    '''
    self._stdin に FCGI_STDIN から受信した内容を保存する。
    この際、サイズにより一時ファイルに出力した tempfile を設定する。
    '''
    def _need_stdin(self):
        if not self._stdin is None:
            # do once
            return

        try:
            colen = 0

            if protocol.FCGI_PARAMSKEY_CONTENT_LENGTH in self.params:
                colen = int(self.params[protocol.FCGI_PARAMSKEY_CONTENT_LENGTH] or 0)

            if colen > self.context.max_stdio_mem:
                # メモリ保存が許可された範囲を超えていたら保存先をファイルにする
                tmpf = tempfile.NamedTemporaryFile('wb', delete=False, prefix='pyfastcgi-stdin-', suffix='.tmp', dir=self.context.temp_dir)
                self._stdin = tmpf

            else:
                self._stdin = bytearray(colen)
                self.stdin_fixed_len = colen

            for data in self.each_stdin():
                with memoryview(data) as mem:
                    nmem = len(mem)

                    tstdin = pyfastcgi.stdio_type(self._stdin)
                    if tstdin == pyfastcgi.StdioType.MEMORY:
                        do_copy = True
                        nstdin = len(self._stdin)

                        if self.stdin_fixed_len > 0:
                            # バッファに余白があることを確認
                            capacity = nstdin - self.stdin_pos
                            assert capacity >= nmem

                        else:
                            if nstdin + nmem > self.context.max_stdio_mem:
                                # メモリ保存が許可された範囲を超えたらファイルに書き出す
                                do_copy = False

                                # 現在のデータを書き出し
                                tmpf = tempfile.NamedTemporaryFile('wb', delete=False, prefix='pyfastcgi-stdin-', suffix='.tmp', dir=self.context.temp_dir)
                                tmpf.write(self._stdin)
                                tmpf.write(mem)

                                # 次からはファイル出力に変更
                                self._stdin = tmpf

                        if do_copy:
                            self._stdin[self.stdin_pos:self.stdin_pos+nmem] = mem

                    elif tstdin == pyfastcgi.StdioType.TMPFILE:
                        self._stdin.write(mem)

                    else:
                        assert False

                    self.stdin_pos += nmem
            # end-for

        finally:
            if pyfastcgi.stdio_type(self._stdin) == pyfastcgi.StdioType.TMPFILE:
                self._stdin.close()

    @property
    def stdin(self):
        self._need_stdin()
        return self._stdin

    '''
    self.stdin を直接参照すると型を意識しなければならないので open_stdin() により
    メモリアクセスできるようにする
    '''
    @contextmanager
    def open_stdin(self):
        self._need_stdin()

        v = None
        f = None
        m = None

        try:
            y = None
            tstdin = pyfastcgi.stdio_type(self._stdin)

            if tstdin == pyfastcgi.StdioType.MEMORY:
                v = memoryview(self._stdin)
                y = v

            elif tstdin == pyfastcgi.StdioType.TMPFILE:
                f = open(self._stdin.name, 'rb')

            elif tstdin == pyfastcgi.StdioType.PATH:
                f = self._stdin.open('rb')

            else:
                assert False

            if not f is None:
                m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                y = m

            assert not y is None

            yield y

        finally:
            if not v is None:
                v.release()

            if not m is None:
                m.close()

            if not f is None:
                f.close()

    def write_stdin_to_file(self, wpath:str):
        self._need_stdin()

        tstdin = pyfastcgi.stdio_type(self._stdin)

        if tstdin == pyfastcgi.StdioType.MEMORY:
            with open(wpath, 'wb') as f:
                if not self._stdin is None:
                    f.write(self._stdin)

        elif tstdin == pyfastcgi.StdioType.TMPFILE:
            if os.path.exists(wpath):
                print(f'unlink {wpath=}', file=sys.stderr)
                os.unlink(wpath)

            assert self._stdin.closed
            os.rename(self._stdin.name, wpath)

            # 一時ファイルを永続ファイルとして移動したので pathlib に変更して
            # 終了時に削除されないようにする
            self._stdin = pathlib.Path(wpath)

        elif tstdin == pyfastcgi.StdioType.PATH:
            rpath = str(self._stdin)

            if not os.path.samefile(rpath, wpath):
                shutil.copyfile(rpath, wpath)

        else:
            assert False


# EOF
