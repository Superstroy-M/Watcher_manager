"""
Работа с S3-совместимым хранилищем (Timeweb Cloud Storage).
Используется для хранения скриншотов.
"""
import os
import io
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger("s3")

S3_ENDPOINT = os.getenv("S3_ENDPOINT_URL", "https://s3.twcstorage.ru")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")
S3_BUCKET = os.getenv("S3_BUCKET", "watcher")
S3_REGION = os.getenv("S3_REGION", "ru-1-hot")
SCREENSHOT_STORAGE = os.getenv("SCREENSHOT_STORAGE", "s3")

_client = None


def get_s3():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION,
            config=Config(signature_version="s3v4"),
        )
    return _client


def upload_screenshot(hostname: str, timestamp: datetime, data: bytes) -> str:
    """
    Загружает скриншот в S3.
    Ключ: screenshots/{hostname}/{YYYY-MM-DD}/{HH-MM-SS}.jpg
    Возвращает URL для просмотра через наш сервер (не прямой S3 URL).
    """
    day = timestamp.strftime("%Y-%m-%d")
    time_str = timestamp.strftime("%H-%M-%S")
    key = f"screenshots/{hostname}/{day}/{time_str}.jpg"

    try:
        get_s3().put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=data,
            ContentType="image/jpeg",
        )
        logger.debug(f"Uploaded screenshot: {key}")
    except ClientError as e:
        logger.error(f"S3 upload failed: {e}")
        raise

    return key


def get_screenshot_url(key: str) -> str:
    """Генерирует presigned URL для просмотра скриншота (действует 1 час)."""
    try:
        url = get_s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=3600,
        )
        return url
    except Exception as e:
        logger.error(f"Presigned URL failed: {e}")
        return ""


def list_screenshots(hostname: str, day: str) -> list[dict]:
    """Список скриншотов за день. Возвращает [{time, key, url}, ...]"""
    prefix = f"screenshots/{hostname}/{day}/"
    try:
        paginator = get_s3().get_paginator("list_objects_v2")
        result = []
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                time_str = key.split("/")[-1].replace(".jpg", "").replace("-", ":")
                result.append({
                    "time": time_str,
                    "key": key,
                    "url": f"/api/screenshot/view?key={key}",
                    "size": obj["Size"],
                })
        return sorted(result, key=lambda x: x["time"])
    except ClientError:
        return []


def list_screenshot_days(hostname: str) -> list[str]:
    """Список дней у которых есть скриншоты для данного хоста."""
    prefix = f"screenshots/{hostname}/"
    try:
        result = get_s3().list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=prefix,
            Delimiter="/",
        )
        days = []
        for cp in result.get("CommonPrefixes", []):
            day = cp["Prefix"].rstrip("/").split("/")[-1]
            if day:
                days.append(day)
        return sorted(days, reverse=True)
    except ClientError:
        return []


def delete_old_screenshots(hostname: str, before_day: str):
    """Удаляет скриншоты старше указанной даты."""
    days = list_screenshot_days(hostname)
    for day in days:
        if day < before_day:
            prefix = f"screenshots/{hostname}/{day}/"
            try:
                objs = get_s3().list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
                keys = [{"Key": o["Key"]} for o in objs.get("Contents", [])]
                if keys:
                    get_s3().delete_objects(Bucket=S3_BUCKET, Delete={"Objects": keys})
                    logger.info(f"Deleted {len(keys)} screenshots from {hostname}/{day}")
            except ClientError as e:
                logger.warning(f"Delete failed: {e}")
