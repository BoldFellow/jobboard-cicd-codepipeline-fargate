import boto3
from boto3.dynamodb.conditions import Key

_resource = None


def _get():
    global _resource
    if _resource is None:
        _resource = boto3.resource("dynamodb")
    return _resource


def _table(name):
    return _get().Table(name)


def put_item(table_name, item):
    _table(table_name).put_item(Item=item)


def get_item(table_name, key):
    return _table(table_name).get_item(Key=key).get("Item")


def delete_item(table_name, key):
    _table(table_name).delete_item(Key=key)


def scan_items(table_name):
    return _table(table_name).scan().get("Items", [])


def query_by_gsi(table_name, index_name, key_name, key_value):
    resp = _table(table_name).query(
        IndexName=index_name,
        KeyConditionExpression=Key(key_name).eq(key_value),
    )
    return resp.get("Items", [])
