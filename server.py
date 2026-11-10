"""Servidor web do sistema (o embutido do Werkzeug, uma thread por conexão)."""
from werkzeug.serving import make_server as werkzeug_server


def make_server(app, host, port, cert_files=None):
    """Servidor pronto para serve_forever(). cert_files = (cert.pem, key.pem) liga o https."""
    return werkzeug_server(host, port, app, threaded=True, ssl_context=cert_files)
