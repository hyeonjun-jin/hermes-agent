"""Scrub OpenAlex query authentication from HTTPX log arguments, never from actual requests."""
import logging
import re

import httpx


class QueryCredentialFilter(logging.Filter):
    def filter(self, record):
        def redact(value):
            if isinstance(value, httpx.URL):
                return str(value.copy_remove_param('api_key'))
            if isinstance(value, str):
                return re.sub(r'(api_key=)[^&\s\"\']+', r'\1[REDACTED]', value)
            if isinstance(value, tuple):
                return tuple(redact(child) for child in value)
            if isinstance(value, dict):
                return {key: redact(child) for key, child in value.items()}
            return value
        record.msg = redact(record.msg)
        record.args = redact(record.args)
        return True


def protect_query_logging():
    logger = logging.getLogger('httpx')
    if not any(isinstance(value, QueryCredentialFilter) for value in logger.filters):
        logger.addFilter(QueryCredentialFilter())
