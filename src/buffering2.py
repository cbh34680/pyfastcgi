import os
import sys
import pathlib
import socket
import collections
import pyfastcgi
import pyfastcgi.listener
import pyfastcgi.responders
import pyfastcgi.responders.buffering as buffering


class JsResponder(buffering.BufferingResponder):
    def make_response(self):
        return pyfastcgi.Response({'Status': '200 OK', 'Content-Type': 'text/javascript'}, '// JS-2')


class CssResponder(buffering.BufferingResponder):
    def make_response(self):
        return pyfastcgi.Response({'Status': '200 OK', 'Content-Type': 'text/css'}, '// CSS-2')


class JpegResponder(buffering.BufferingResponder):
    def make_response(self):
        jpgpath = pathlib.Path(os.path.dirname(__file__)) / '..' / 'data' / 'world-political-map-2020.jpg'
        return pyfastcgi.Response({'Status': '200 OK', 'Content-Type': 'text/css'}, jpgpath)


class PostResponder(buffering.BufferingResponder):
    def make_response(self):
        with self.open_stdin() as mem:
            print(f'{len(mem)=}', file=sys.stderr)

            if len(mem) > 1024:
                cobody = f'{len(mem)}'

            else:
                cobody = self.stdin

        return pyfastcgi.Response({'Status': '200 OK', 'Content-Type': 'text/plain'}, cobody)


def ResponderSelector(context:pyfastcgi.Context, conn:socket.socket, client:tuple, reqid:int, params:collections.Mapping):
    print(f'{__file__}: {os.getpid()=} from {client=}', file=sys.stderr)

    if params['REQUEST_METHOD'] == 'GET':
        requri = params['REQUEST_URI']

        if requri[-3:] == '.js':
            responder = JsResponder

        elif requri[-4:] == '.css':
            responder = CssResponder

        elif requri[-4:] == '.jpg':
            responder = JpegResponder

        else:
            responder = pyfastcgi.responders.NotFoundResponder

    else:
        responder = PostResponder

    return responder(context, conn, client, reqid, params)


if __name__ == '__main__':
    def _main():
        config = pyfastcgi.parse_args()
        context = pyfastcgi.make_context(config, responder_factory=ResponderSelector)
        pyfastcgi.listener.start(context)

    _main()

# EOF
