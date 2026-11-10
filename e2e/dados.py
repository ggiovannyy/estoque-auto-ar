"""Nomes e códigos únicos: todos os testes de interface usam o mesmo banco."""
import itertools
import time

_ids = itertools.count(1)


def unique(prefix):
    return f"{prefix} {next(_ids):04d}"


def unique_barcode():
    return f"78{time.time_ns() % 10**11:011d}"
