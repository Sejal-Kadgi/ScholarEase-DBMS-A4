import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from Module_A.database.bplustree import BPlusTree


class Table:
    def __init__(self, name, schema, order=8, search_key=None):
        self.name       = name
        self.schema     = schema        # list of column names
        self.order      = order
        self.search_key = search_key    # primary key column
        self.data       = BPlusTree(order=order)

    def _validate(self, record):
        """
        Validate that every declared schema column is present in the record.
        NULL / None values are allowed (mirrors SQL NULLable columns such as
        ApprovedAmount, WhatsAppNo, Image, Remarks, RationCardNo, etc.).
        """
        for col in self.schema:
            if col not in record:
                raise ValueError(
                    f"Missing column '{col}' in record for table '{self.name}'. "
                    f"Expected columns: {self.schema}"
                )

    def insert(self, record):
        self._validate(record)
        key = record[self.search_key]
        self.data.insert(key, record)

    def get(self, key):
        return self.data.search(key)

    def get_all(self):
        return [v for _, v in self.data.get_all()]

    def update(self, key, new_record):
        self._validate(new_record)
        return self.data.update(key, new_record)

    def delete(self, key):
        self.data.delete(key)

    def range_query(self, start, end):
        return [v for _, v in self.data.range_query(start, end)]