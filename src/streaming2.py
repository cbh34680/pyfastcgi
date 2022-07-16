import os
import sys
import socket
import collections
import html
import pprint
import pyfastcgi
import pyfastcgi.listener
import pyfastcgi.responders
import pyfastcgi.responders.streaming as streaming


class PostResponder(streaming.StreamingResponder):
    def on_request(self):

        with self.open_stdout({'Content-Type': 'text/html; charset=utf-8'}) as stream:

            stream.write(f'<html><body>')
            stream.write(f'<pre>')

            stream.write(html.escape(pprint.pformat(self.params)))

            stream.write(f'</pre><hr /><pre>')

            for data in self.each_stdin():
                data = html.escape(data.decode('utf-8')).encode('utf-8')
                stream.write(data)

            stream.write(f'</pre></body></html>')


def ResponderSelector(context:pyfastcgi.Context, conn:socket.socket, client:tuple, reqid:int, params:collections.Mapping):
    print(f'{__file__}: {os.getpid()=} from {client=}', file=sys.stderr)

    if params['REQUEST_METHOD'] == 'POST':
        responder = PostResponder
    else:
        responder = pyfastcgi.responders.MethodNotAllowedResponder

    return responder(context, conn, client, reqid, params)


if __name__ == '__main__':
    def _main():
        config = pyfastcgi.parse_args()
        context = pyfastcgi.make_context(config, responder_factory=ResponderSelector)
        pyfastcgi.listener.start(context)

    _main()

# EOF
