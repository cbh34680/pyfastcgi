import os
import sys
import socket
import collections
import pyfastcgi
import pyfastcgi.responders.streaming as streaming
import pyfastcgi.responders
import pyfastcgi.listener


class Responder(streaming.StreamingResponder):
    def on_request(self):
        resp_header = {
            'Content-Type': 'text/plain; charset=utf-8'
        }

        with self.open_stdout(resp_header) as output:
            for input in self.each_stdin():
                output.write(input)


def ResponderSelector(context:pyfastcgi.Context, conn:socket.socket, client:tuple, reqid:int, params:collections.Mapping):
    print(f'{__file__}: {os.getpid()=} from {client=}', file=sys.stderr)

    if params['REQUEST_METHOD'] == 'POST':
        responder = Responder
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
