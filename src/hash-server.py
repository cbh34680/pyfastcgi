import os
import sys
import socket
import collections
import hashlib
import pyfastcgi
import pyfastcgi.listener
import pyfastcgi.responders
import pyfastcgi.responders.buffering as buffering


class Responder(buffering.BufferingResponder):
    def make_response(self):
        resp_header = {
            'Content-Type': 'text/plain; charset=utf-8'
        }

        m = hashlib.md5()

        for input in self.each_stdin():
            m.update(input)

        return pyfastcgi.Response(resp_header, m.hexdigest())


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
