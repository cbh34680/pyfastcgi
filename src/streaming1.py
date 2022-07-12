import os
import sys
import socket
import collections
import pyfastcgi
import pyfastcgi.responders.streaming as streaming
import pyfastcgi.responders
import pyfastcgi.listener


class PostResponder(streaming.StreamingResponder):
    def on_request(self):
        #1/0

        with self.open_stdout({'Content-Type': 'text/plain; charset=utf-8'}) as stream:
            #1/0

            for data in self.each_stdin():
                stream.write(data)


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
