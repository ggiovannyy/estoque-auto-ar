"""Servidor web do sistema (o embutido do Werkzeug, uma thread por conexão).

Com https, o Werkzeug faz o handshake TLS dentro do accept(), na única thread que aceita conexões, e sem tempo
limite: uma conexão aberta que não manda nada (celular que perdeu o Wi-Fi, varredura de rede) travava o sistema
para todos. Aqui o handshake fica para a thread de cada conexão, e toda conexão parada é fechada depois de
CONNECTION_TIMEOUT_SECONDS.
"""
import ssl

from werkzeug.serving import WSGIRequestHandler
from werkzeug.serving import make_server as werkzeug_server

CONNECTION_TIMEOUT_SECONDS = 30


class _RequestHandler(WSGIRequestHandler):
    @property
    def timeout(self):  # o socketserver aplica ao socket da conexão antes de ler qualquer coisa
        return CONNECTION_TIMEOUT_SECONDS


def make_server(app, host, port, cert_files=None):
    """Servidor pronto para serve_forever(). cert_files = (cert.pem, key.pem) liga o https."""
    server = werkzeug_server(host, port, app, threaded=True, request_handler=_RequestHandler)
    if cert_files:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*cert_files)
        # Sem handshake no accept(): ele acontece na primeira leitura, já na thread da conexão.
        server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
        server.ssl_context = context  # o Werkzeug usa para informar https e tratar erros de TLS
    return server
