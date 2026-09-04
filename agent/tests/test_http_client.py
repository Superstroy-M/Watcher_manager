import requests

from http_client import is_transport_error


def test_is_transport_error_for_connection_and_timeout():
    assert is_transport_error(requests.exceptions.ConnectionError("down")) is True
    assert is_transport_error(requests.exceptions.Timeout("slow")) is True
    assert is_transport_error(OSError("network down")) is True


def test_is_transport_error_false_for_http_response_errors():
    response = requests.Response()
    response.status_code = 500
    assert is_transport_error(requests.exceptions.HTTPError(response=response)) is False


def test_is_transport_error_false_for_generic_exception():
    assert is_transport_error(AttributeError("'srcdc'")) is False
    assert is_transport_error(ValueError("bad payload")) is False
