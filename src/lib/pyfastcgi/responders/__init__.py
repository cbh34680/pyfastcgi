import http.client
import pyfastcgi
import pyfastcgi.protocol as protocol
from dataclasses import dataclass


'''
_ErrorResponder
'''
class _ErrorResponder(pyfastcgi._BaseResponder):
    @property
    def http_code(self) -> int:
        ...

    def do_response(self):
        code = self.http_code or 500
        mesg = http.client.responses[code]
        herr = f'{code} {mesg}'

        body = f'<!doctype html><html><body>{herr}</body></html>'.encode('utf-8')
        nbody = len(body)

        contentData = f'''
Status: {herr}\r
Content-Type: text/html; charset=utf-8\r
Content-Length: {nbody}\r
\r
'''.lstrip().encode('utf-8') + body

        pyfastcgi.send_record(self.conn, protocol.FCGI_STDOUT, self.requestId, contentData=contentData)
        pyfastcgi.send_record(self.conn, protocol.FCGI_STDOUT, self.requestId)

        return 1


# 400
class BadRequestResponder(_ErrorResponder):
    @property
    def http_code(self) -> int:
        return http.client.BAD_REQUEST

# 404
class NotFoundResponder(_ErrorResponder):
    @property
    def http_code(self) -> int:
        return http.client.NOT_FOUND

# 405
class MethodNotAllowedResponder(_ErrorResponder):
    @property
    def http_code(self) -> int:
        return http.client.METHOD_NOT_ALLOWED

# 500
class InternalServerErrorResponder(_ErrorResponder):
    ...

# 501
class NotImplementedResponder(_ErrorResponder):
    @property
    def http_code(self) -> int:
        return http.client.NOT_IMPLEMENTED

# 503
class ServiceUnavailableResponder(_ErrorResponder):
    @property
    def http_code(self) -> int:
        return http.client.SERVICE_UNAVAILABLE


# EOF
