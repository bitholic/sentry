from __future__ import absolute_import

import os
import time
import posixpath
import nos
from django.core.files.storage import Storage
from django.core.files.base import File
from django.utils.encoding import force_text, force_bytes
from django.utils.six import BytesIO
from datetime import datetime


def clean_name(name):
    """
    Cleans the name so that Windows style paths work
    """
    # Normalize Windows style paths
    cleaned_name = posixpath.normpath(name).replace("\\", "/")

    # os.path.normpath() can strip trailing slashes so we implement
    # a workaround here.
    if name.endswith("/") and not cleaned_name.endswith("/"):
        # Add a trailing slash as it was stripped.
        cleaned_name = cleaned_name + "/"

    # Given an empty string, os.path.normpath() will return ., which we don't want
    if cleaned_name == ".":
        cleaned_name = ""

    return cleaned_name


def safe_join(base, *paths):
    """
    A version of django.utils._os.safe_join for nos paths.
    Joins one or more path components to the base path component
    intelligently. Returns a normalized version of the final path.
    The final path must be located inside of the base path component
    (otherwise a ValueError is raised).
    Paths outside the base path indicate a possible security
    sensitive operation.
    """
    base_path = force_text(base)
    base_path = base_path.rstrip("/")
    paths = [force_text(p) for p in paths]

    final_path = base_path + "/"
    for path in paths:
        _final_path = posixpath.normpath(posixpath.join(final_path, path))
        # posixpath.normpath() strips the trailing /. Add it back.
        if path.endswith("/") or _final_path + "/" == final_path:
            _final_path += "/"
        final_path = _final_path
    if final_path == base_path:
        final_path += "/"
    return final_path.lstrip("/")


class NeteaseCloudFile(File):
    def __init__(self, name, mode, storage):
        self.name = name
        self._mode = mode
        self._storage = storage
        self._file = None
        self._is_dirty = False

    def _get_file(self):
        if self._file is None:
            # with metrics.timer("filestore.read", instance="nos"):
            self._file = BytesIO()
            if "r" in self._mode:
                self._is_dirty = False
                self._file.write(self._storage.download(self.name).read())
                self._file.seek(0)

        return self._file

    def _set_file(self, value):
        self._file = value

    file = property(_get_file, _set_file)

    def read(self, *args, **kwargs):
        if "r" not in self._mode:
            raise AttributeError("File was not opened in read mode.")
        return super(NeteaseCloudFile, self).read(*args, **kwargs)

    def write(self, content):
        if "w" not in self._mode:
            raise AttributeError("File was not opened in write mode.")
        self._is_dirty = True
        return super(NeteaseCloudFile, self).write(force_bytes(content))

    @property
    def _buffer_file_size(self):
        pos = self.file.tell()
        self.file.seek(0, os.SEEK_END)
        length = self.file.tell()
        self.file.seek(pos)
        return length

    def _flush_write_buffer(self):
        """
        Flushes the write buffer.
        """
        if self._buffer_file_size:
            self.file.seek(0)
            self._storage.upload(self.name, self.file.read())

    def close(self):
        if self._is_dirty:
            self._flush_write_buffer()

        if self._file is not None:
            self._file.close()
            self._file = None


class NeteaseObjectStorage(Storage):
    """
    NOS impl
    """
    access_key = None
    secret_key = None
    end_point = None
    bucket = None
    location = None
    base_url = None

    def __init__(self, **settings):
        for name, value in settings.items():
            if hasattr(self, name):
                setattr(self, name, value)

        self.location = (self.location or '').lstrip("/")
        self._client = None

    def _normalize_name(self, name):
        if self.location and name.startswith(self.location):
            return name
        return safe_join(self.location, name)

    @property
    def client(self):
        if self._client is None:
            self._client = nos.Client(self.access_key, self.secret_key, end_point=self.end_point)
        return self._client

    def download(self, name):
        name = self._normalize_name(name)
        result = self.client.get_object(self.bucket, name)
        return result.get("body")

    def upload(self, name, content):
        cleaned_name = clean_name(name)
        name = self._normalize_name(cleaned_name)
        self.client.put_object(self.bucket, name, content)
        return cleaned_name

    def _open(self, name, mode="rb"):
        name = self._normalize_name(clean_name(name))
        return NeteaseCloudFile(name, mode, self)

    def _save(self, name, content):
        content.seek(0, os.SEEK_SET)
        cleaned_name = self.upload(name, content.read())
        return cleaned_name

    def delete(self, name):
        name = self._normalize_name(clean_name(name))
        self.client.delete_object(self.bucket, name)

    def exists(self, name):
        if not name:
            name = ""
        name = self._normalize_name(clean_name(name))
        try:
            self.client.head_object(self.bucket, name)
        except nos.exceptions.NotFoundError:
            return False
        except nos.exceptions.ForbiddenError:
            return False
        return True

    def listdir(self, path):
        path = self._normalize_name(clean_name(path))
        if path and not path.endswith("/"):
            path += "/"
        object_lists = self.client.list_objects(self.bucket, prefix=path)

        files = []
        dirs = set()
        base_parts = path.split("/")[:-1]
        for item in object_lists["response"].findall("Contents"):
            parts = item.find("Key").text.split("/")
            parts = parts[len(base_parts):]
            if len(parts) == 1 and parts[0]:
                # File
                files.append(parts[0])
            elif len(parts) > 1 and parts[0]:
                # Directory
                dirs.add(parts[0])
        return list(dirs), files

    def size(self, name):
        name = self._normalize_name(clean_name(name))
        try:
            res = self.client.head_object(self.bucket, name)
            return res["content_length"]
        except nos.exceptions.ServiceException:
            return 0

    def url(self, name):
        name = self._normalize_name(clean_name(name))
        return "{base_url}/{path}".format(base_url=self.base_url, location=self.location, path=name)

    def accessed_time(self, name):
        # fixme?: no corresponding nos api
        return self.modified_time(name)

    def created_time(self, name):
        # fixme?: no corresponding nos api
        return self.modified_time(name)

    def modified_time(self, name):
        name = self._normalize_name(clean_name(name))
        try:
            res = self.client.head_object(self.bucket, name)
            return datetime.fromtimestamp(
                time.mktime(time.strptime(res["last_modified"], "%a, %d %b %Y %H:%M:%S %Z"))
            )
        except nos.exceptions.ServiceException:
            return 0
