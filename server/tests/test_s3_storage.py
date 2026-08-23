"""
Тесты s3_storage.py — работа с S3-совместимым хранилищем.
Реальные HTTP-вызовы замокированы через boto3.
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def reset_s3_client():
    """Сбрасываем singleton S3-клиент перед каждым тестом."""
    import s3_storage
    old_client = s3_storage._client
    s3_storage._client = None
    yield
    s3_storage._client = old_client


@pytest.fixture
def mock_s3(mocker):
    """Мок boto3-клиента."""
    client_mock = MagicMock()
    mocker.patch("s3_storage.boto3.client", return_value=client_mock)
    return client_mock


# ══════════════════════════════════════════════════════════════════════════════
#  upload_screenshot
# ══════════════════════════════════════════════════════════════════════════════

class TestUploadScreenshot:

    def test_key_format(self, mock_s3):
        from s3_storage import upload_screenshot
        ts = datetime(2024, 1, 15, 9, 30, 45)
        key = upload_screenshot("test-pc", ts, b"\xff\xd8\xff")
        assert key == "screenshots/test-pc/2024-01-15/09-30-45.jpg"

    def test_calls_put_object(self, mock_s3):
        from s3_storage import upload_screenshot
        ts = datetime(2024, 3, 10, 14, 5, 0)
        upload_screenshot("myhost", ts, b"data")
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["ContentType"] == "image/jpeg"
        assert call_kwargs["Body"] == b"data"

    def test_key_in_correct_bucket(self, mock_s3, monkeypatch):
        import s3_storage
        monkeypatch.setattr(s3_storage, "S3_BUCKET", "test-bucket")
        from s3_storage import upload_screenshot
        ts = datetime(2024, 1, 1, 0, 0, 0)
        upload_screenshot("pc", ts, b"img")
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"

    def test_raises_on_s3_error(self, mock_s3):
        from botocore.exceptions import ClientError
        from s3_storage import upload_screenshot
        mock_s3.put_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "bucket not found"}}, "put_object"
        )
        with pytest.raises(ClientError):
            upload_screenshot("pc", datetime.utcnow(), b"data")


# ══════════════════════════════════════════════════════════════════════════════
#  get_screenshot_url
# ══════════════════════════════════════════════════════════════════════════════

class TestGetScreenshotUrl:

    def test_returns_presigned_url(self, mock_s3):
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/signed"
        from s3_storage import get_screenshot_url
        url = get_screenshot_url("screenshots/pc/2024-01-15/09-00-00.jpg")
        assert url == "https://s3.example.com/signed"

    def test_returns_empty_string_on_error(self, mock_s3):
        mock_s3.generate_presigned_url.side_effect = Exception("S3 error")
        from s3_storage import get_screenshot_url
        url = get_screenshot_url("some/key.jpg")
        assert url == ""

    def test_expiry_1_hour(self, mock_s3):
        mock_s3.generate_presigned_url.return_value = "https://example.com/url"
        from s3_storage import get_screenshot_url
        get_screenshot_url("key.jpg")
        call_kwargs = mock_s3.generate_presigned_url.call_args[1]
        assert call_kwargs["ExpiresIn"] == 3600


# ══════════════════════════════════════════════════════════════════════════════
#  list_screenshots
# ══════════════════════════════════════════════════════════════════════════════

class TestListScreenshots:

    def _make_paginator(self, keys: list[str]) -> MagicMock:
        contents = [{"Key": k, "Size": 1024} for k in keys]
        page = {"Contents": contents}
        paginator = MagicMock()
        paginator.paginate.return_value = [page]
        return paginator

    def test_returns_sorted_list(self, mock_s3):
        keys = [
            "screenshots/pc/2024-01-15/10-00-00.jpg",
            "screenshots/pc/2024-01-15/09-00-00.jpg",
            "screenshots/pc/2024-01-15/11-00-00.jpg",
        ]
        mock_s3.get_paginator.return_value = self._make_paginator(keys)
        from s3_storage import list_screenshots
        result = list_screenshots("pc", "2024-01-15")
        times = [r["time"] for r in result]
        assert times == sorted(times)

    def test_time_format_parsed(self, mock_s3):
        keys = ["screenshots/pc/2024-01-15/09-30-15.jpg"]
        mock_s3.get_paginator.return_value = self._make_paginator(keys)
        from s3_storage import list_screenshots
        result = list_screenshots("pc", "2024-01-15")
        assert result[0]["time"] == "09:30:15"

    def test_empty_on_client_error(self, mock_s3):
        from botocore.exceptions import ClientError
        mock_s3.get_paginator.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": ""}}, "list_objects_v2"
        )
        from s3_storage import list_screenshots
        result = list_screenshots("pc", "2024-01-15")
        assert result == []

    def test_empty_prefix_returns_empty(self, mock_s3):
        paginator = MagicMock()
        paginator.paginate.return_value = [{}]  # нет Contents
        mock_s3.get_paginator.return_value = paginator
        from s3_storage import list_screenshots
        result = list_screenshots("pc", "2024-01-15")
        assert result == []

    def test_url_field_contains_api_path(self, mock_s3):
        keys = ["screenshots/pc/2024-01-15/10-00-00.jpg"]
        mock_s3.get_paginator.return_value = self._make_paginator(keys)
        from s3_storage import list_screenshots
        result = list_screenshots("pc", "2024-01-15")
        assert "/api/screenshot/view" in result[0]["url"]


# ══════════════════════════════════════════════════════════════════════════════
#  list_screenshot_days
# ══════════════════════════════════════════════════════════════════════════════

class TestListScreenshotDays:

    def test_returns_days_sorted_reverse(self, mock_s3):
        mock_s3.list_objects_v2.return_value = {
            "CommonPrefixes": [
                {"Prefix": "screenshots/pc/2024-01-10/"},
                {"Prefix": "screenshots/pc/2024-01-15/"},
                {"Prefix": "screenshots/pc/2024-01-05/"},
            ]
        }
        from s3_storage import list_screenshot_days
        days = list_screenshot_days("pc")
        assert days == ["2024-01-15", "2024-01-10", "2024-01-05"]

    def test_empty_on_error(self, mock_s3):
        from botocore.exceptions import ClientError
        mock_s3.list_objects_v2.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": ""}}, "list_objects_v2"
        )
        from s3_storage import list_screenshot_days
        assert list_screenshot_days("pc") == []

    def test_no_prefixes_returns_empty(self, mock_s3):
        mock_s3.list_objects_v2.return_value = {}
        from s3_storage import list_screenshot_days
        assert list_screenshot_days("pc") == []


# ══════════════════════════════════════════════════════════════════════════════
#  delete_old_screenshots
# ══════════════════════════════════════════════════════════════════════════════

class TestDeleteOldScreenshots:

    def test_deletes_only_old_days(self, mock_s3):
        mock_s3.list_objects_v2.side_effect = [
            # list_screenshot_days call
            {
                "CommonPrefixes": [
                    {"Prefix": "screenshots/pc/2024-01-01/"},
                    {"Prefix": "screenshots/pc/2024-01-10/"},
                    {"Prefix": "screenshots/pc/2024-01-20/"},
                ]
            },
            # get objects for 2024-01-01 (old)
            {"Contents": [{"Key": "screenshots/pc/2024-01-01/09-00-00.jpg"}]},
        ]
        from s3_storage import delete_old_screenshots
        delete_old_screenshots("pc", "2024-01-10")
        mock_s3.delete_objects.assert_called_once()
        deleted = mock_s3.delete_objects.call_args[1]["Delete"]["Objects"]
        assert len(deleted) == 1
        assert "2024-01-01" in deleted[0]["Key"]

    def test_does_not_delete_recent_days(self, mock_s3):
        mock_s3.list_objects_v2.return_value = {
            "CommonPrefixes": [
                {"Prefix": "screenshots/pc/2024-01-15/"},
                {"Prefix": "screenshots/pc/2024-01-20/"},
            ]
        }
        from s3_storage import delete_old_screenshots
        delete_old_screenshots("pc", "2024-01-10")
        mock_s3.delete_objects.assert_not_called()
