import sys
import collections
import socket
import struct
import traceback
from dataclasses import dataclass


FCGI_HEADER_LEN         = 8
FCGI_VERSION_1          = 1
FCGI_MAX_LENGTH         = 0xffff
FCGI_KEEP_CONN          = 1

FCGI_BEGIN_REQUEST		=  1 # [in]                              */
FCGI_ABORT_REQUEST		=  2 # [in]  (not supported)             */
FCGI_END_REQUEST		=  3 # [out]                             */
FCGI_PARAMS				=  4 # [in]  environment variables       */
FCGI_STDIN				=  5 # [in]  post data                   */
FCGI_STDOUT				=  6 # [out] response                    */
FCGI_STDERR				=  7 # [out] errors                      */
FCGI_DATA				=  8 # [in]  filter data (not supported) */
FCGI_GET_VALUES			=  9 # [in]                              */
FCGI_GET_VALUES_RESULT	= 10 # [out]                             */

FCGI_REQUEST_COMPLETE	= 0
FCGI_CANT_MPX_CONN		= 1
FCGI_OVERLOADED			= 2
FCGI_UNKNOWN_ROLE		= 3

FCGI_ROLE_NAMES = {
    1: 'RESPONDER',
    2: 'AUTHORIZER',
    3: 'FILTER',
}

#PACKET_IO_LEN = FCGI_MAX_LENGTH
PACKET_IO_LEN = 8192
PACKET_IO_CONTENT_LEN = PACKET_IO_LEN - FCGI_HEADER_LEN

assert PACKET_IO_LEN >= FCGI_HEADER_LEN
assert PACKET_IO_LEN <= FCGI_MAX_LENGTH

#
FCGI_PARAMSKEY_CONTENT_TYPE     = 'CONTENT_TYPE'
FCGI_PARAMSKEY_CONTENT_LENGTH   = 'CONTENT_LENGTH'


@dataclass(frozen=True)
class FCGI_RecordHeader:
    version:int
    recordType:int
    requestId:int
    contentLength:int
    paddingLength:int
    reserved:int = 0

    def dump(self) -> bytes:
        hdata = (
            self.version,
            self.recordType,
            self.requestId,
            self.contentLength,
            self.paddingLength,
            self.reserved,
        )

        return struct.pack('>2B2H2B', *hdata)

@dataclass(frozen=True)
class FCGI_Record:
    header:FCGI_RecordHeader
    contentData:bytearray
    paddingData:bytearray

    def dump(self) -> bytes:
        hdata = (
            self.contentData,
            self.paddingData,
        )
        fmt = f'{self.header.contentLength}s{self.header.paddingLength}s'

        return self.header.dump() + struct.pack(fmt, *hdata)

@dataclass(frozen=True)
class FCGI_BeginRequestBody:
    role:int
    flags:int
    reserved:bytes = b'\0\0\0\0\0'

@dataclass(frozen=True)
class FCGI_EndRequestBody:
    appStatus:int
    protocolStatus:int
    reserved:bytes = b'\0\0\0'

    def dump(self) -> bytes:
        hdata = (
            self.appStatus,
            self.protocolStatus,
            self.reserved,
        )

        return struct.pack('>IB3s', *hdata)


def recv_bytes(conn:socket.socket, nrecv:int) -> bytearray:
    remaining = nrecv
    buff = bytearray(nrecv)
    assert conn.getblocking()

    with memoryview(buff) as mem:
        while remaining:
            first = nrecv - remaining
            nread = min(remaining, PACKET_IO_LEN)
            nread = conn.recv_into(mem[first:], nread)

            if nread <= 0:
                '''
                https://docs.python.org/ja/3/library/socket.html
                https://peps.python.org/pep-0475/
                バージョン 3.5 で変更: システムコールが中断されシグナルハンドラが例外を送出しなかった場合、
                このメソッドは InterruptedError 例外を送出する代わりにシステムコールを再試行するようになりました

                --> ブロッキングモードで recv が 0 bytes を返却することはないはず
                '''
                raise ConnectionError()

            remaining -= nread

    return buff


def read_record(conn:socket.socket) -> FCGI_Record:
    buff = recv_bytes(conn, FCGI_HEADER_LEN)

    a = struct.unpack('>2B2H2B', buff)
    header = FCGI_RecordHeader(*a)
    #print(f'{header=}')
    assert header.version == FCGI_VERSION_1
    assert header.contentLength <= FCGI_MAX_LENGTH

    nbuff = header.contentLength + header.paddingLength

    contentData = None
    paddingData = None

    if nbuff:
        buff = recv_bytes(conn, nbuff)

        if header.contentLength:
            contentData = buff[:header.contentLength]

        if header.paddingLength:
            paddingData = buff[header.contentLength:]

    if contentData is None:
        contentData = bytearray()

    if paddingData is None:
        paddingData = bytearray()

    return FCGI_Record(header, contentData, paddingData)


def make_record_header(recordType:int, requestId:int, *, contentLength) -> FCGI_RecordHeader:
    assert contentLength <= FCGI_MAX_LENGTH

    paddingLength = ( ( contentLength + 7 ) & ~7 ) - contentLength

    hdata = (
        FCGI_VERSION_1,
        recordType,
        requestId,
        contentLength,
        paddingLength,
    )

    return FCGI_RecordHeader(*hdata)


def make_record(recordType:int, requestId:int, *, contentData:bytearray, contentLength:int=-1) -> FCGI_Record:
    if contentLength < 0:
        contentLength = len(contentData)

    header = make_record_header(recordType, requestId, contentLength=contentLength)
    paddingData = bytearray(header.paddingLength)

    return FCGI_Record(header, contentData, paddingData)


def make_params(mem:memoryview) -> collections.Mapping:
    params = {}
    nbuff = len(mem)
    pos = 0

    while pos < nbuff:
        a, = struct.unpack('B', mem[pos+0: pos+0+1])
        if a >> 7 == 0:
            nameLength = a

            b, = struct.unpack('B', mem[pos+1: pos+1+1])
            if b >> 7 == 0:
                # FCGI_NameValuePair11
                valueLength = b
                pos += 2

            else:
                # FCGI_NameValuePair14
                mem[pos+1] &= 0x7f
                valueLength, = struct.unpack('>I', mem[pos+1: pos+1+4])
                pos += 5

        else:
            nameLength, = struct.unpack('>I', mem[pos+0: pos+0+4])

            b, = struct.unpack('B', mem[pos+3: pos+3+1])
            if b >> 7 == 0:
                # FCGI_NameValuePair41
                valueLength = b
                pos += 5


            else:
                # FCGI_NameValuePair44
                mem[pos+3] &= 0x7f
                valueLength, = struct.unpack('>I', mem[pos+3: pos+3+4])
                pos += 8

        #print(f'{pos=} {nameLength=} {valueLength=}')

        nameData, = struct.unpack(f'{nameLength}s', mem[pos:pos+nameLength])
        pos += nameLength

        valueData, = struct.unpack(f'{valueLength}s', mem[pos:pos+valueLength])
        pos += valueLength

        nameData = nameData.decode('utf-8')
        valueData = valueData.decode('utf-8')

        #print(f'{nameData=} {valueData=}')
        params[nameData] = valueData

    return params


def send_record(conn:socket.socket, recordType:int, requestId:int, *, contentData=b'', contentLength=-1) -> int:
    assert conn.getblocking()

    cdtype = type(contentData)
    assert cdtype in (bytes, bytearray)

    if contentLength < 0:
        contentLength = len(contentData)

    sum_send = 0

    if contentLength > PACKET_IO_LEN:
        remaining = contentLength

        with memoryview(contentData) as mem:
            while remaining:
                nsend = min(remaining, PACKET_IO_LEN)
                first = contentLength - remaining

                with memoryview(mem.obj[first:first+nsend]) as part:
                    record = make_record(recordType, requestId, contentData=part.obj)
                    a = record.dump()
                    sum_send += len(a)
                    conn.sendall(a)

                remaining -= nsend

    else:
        record = make_record(recordType, requestId, contentData=contentData, contentLength=contentLength)
        a = record.dump()
        sum_send = len(a)
        conn.sendall(a)

    assert sum_send >= contentLength

    return sum_send


def close_socket(conn:socket.socket):
    if conn.fileno() <= 0:
        return False

    '''
    都合により stdin のデータが受信しきれていないまま close を実行すると
    Web サーバ上の fastcgi (リクエストの送信側) のソケットが
    強制的な close となるため、全て読み飛ばす
    '''

    try:
        '''
        php-src-master/main/fastcgi.c
        void fcgi_close(fcgi_request *req, int force, int destroy)
        '''
        conn.shutdown(socket.SHUT_WR)
        conn.settimeout(0.1)
        buff = bytearray(PACKET_IO_LEN)

        nread = 1
        while nread > 0:
            nread = conn.recv_into(buff)

    except:
        # ignore
        traceback.print_exception(*sys.exc_info(), file=sys.stderr)

    finally:
        try:
            if conn.fileno() > 0:
                conn.close()
        except:
            # ignore
            traceback.print_exception(*sys.exc_info(), file=sys.stderr)

    return True


# EOF