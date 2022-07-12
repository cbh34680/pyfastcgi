import os
import sys
import pathlib
import tempfile
import pyfastcgi
import pyfastcgi.responders.buffering as buffering
import pyfastcgi.listener


class Responder(buffering.BufferingResponder):
    def do_get(self):
        requri = self.params['REQUEST_URI']

        if requri[-3:] == '.js':
            cotype = 'text/javascript'
            cobody = '// js'

        elif requri[-4:] == '.css':
            cotype = 'text/css'

            tmpf = tempfile.NamedTemporaryFile('w', delete=False, encoding='utf-8', prefix='pyfastcgi-stdout-', suffix='.tmp', dir=self.context.temp_dir)
            tmpf.write('// css')
            tmpf.close()

            cobody = tmpf

        elif requri[-4:] == '.jpg':
            cotype = 'image/jpeg'

            jpgpath = pathlib.Path(os.path.dirname(__file__)) / '..' / 'data' / 'world-political-map-2020.jpg'
            cobody = jpgpath

        elif requri[-5:] == '.serr':
            1/0

        elif requri[-5:] == '.aerr':
            raise Exception('aaa')

        return cotype, cobody

    def do_post(self):
        cotype = 'text/plain'

        with self.open_stdin() as mem:
            print(f'{len(mem)=}', file=sys.stderr)

            if len(mem) > 1024:
                cobody = f'{len(mem)}'

            else:
                cobody = self._stdin

        wpath = os.path.join(self.context.temp_dir, f'renamed-{os.getpid()}.tmp')
        self.write_stdin_to_file(wpath)

        return cotype, cobody

    def make_response(self):
        print(f'{__file__}: {os.getpid()=} from {self.client=}', file=sys.stderr)
        #pprint.pprint(params)

        if self.params['REQUEST_METHOD'] == 'GET':
            cotype, cobody = self.do_get()

        else:
            cotype, cobody = self.do_post()

        headers = {
            'Status': '200 OK',
            'Content-Type': cotype,
        }

        return pyfastcgi.Response(headers, cobody)


    #def on_stdin_data(self, mem):
    #    ...


def event_handler(context:pyfastcgi.Context, event:pyfastcgi.Event):
    print(f'{__file__}: {event.name=} {type(event.data)=}', file=sys.stderr)

    if event.name == 'IDLE':
        print(f'{__file__}: {context.stats=}', file=sys.stderr)


if __name__ == '__main__':
    def _main():
        config = pyfastcgi.parse_args()
        context = pyfastcgi.make_context(config, event_handler=event_handler, responder_factory=Responder)
        pyfastcgi.listener.start(context)

    _main()

# EOF
