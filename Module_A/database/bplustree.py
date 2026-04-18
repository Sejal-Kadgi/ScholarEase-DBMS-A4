import math

try:
    from graphviz import Digraph
except ImportError:
    Digraph = None

class BPlusTreeNode:
    def __init__(self, order, is_leaf=True):
        self.order    = order
        self.is_leaf  = is_leaf
        self.keys     = []        # sorted keys
        self.values   = []        # leaf-only: parallel list of record values
        self.children = []        # internal-only: child node pointers
        self.next     = None      # leaf-only: pointer to next leaf

    def is_full(self):
        return len(self.keys) >= self.order - 1

class BPlusTree:
    def __init__(self, order=8):
        self.order = order
        self.root  = BPlusTreeNode(order, is_leaf=True)

    def search(self, key):
        return self._search(self.root, key)

    def _search(self, node, key):
        if node.is_leaf:
            for i, k in enumerate(node.keys):
                if k == key:
                    return node.values[i]
            return None
        for i, k in enumerate(node.keys):
            if key < k:
                return self._search(node.children[i], key)
        return self._search(node.children[-1], key)


    def insert(self, key, value):
        root = self.root
        if root.is_full():
            new_root = BPlusTreeNode(self.order, is_leaf=False)
            new_root.children.append(root)
            self._split_child(new_root, 0)
            self.root = new_root
        self._insert_non_full(self.root, key, value)

    def _insert_non_full(self, node, key, value):
        if node.is_leaf:
            i = 0
            while i < len(node.keys) and key > node.keys[i]:
                i += 1
            node.keys.insert(i, key)
            node.values.insert(i, value)
        else:
            i = 0
            while i < len(node.keys) and key > node.keys[i]:
                i += 1
            if i >= len(node.children):
                i = len(node.children) - 1
            child = node.children[i]
            if child.is_full():
                self._split_child(node, i)
                if key > node.keys[i]:
                    i += 1
            self._insert_non_full(node.children[i], key, value)

    def _split_child(self, parent, index):
        node     = parent.children[index]
        new_node = BPlusTreeNode(self.order, is_leaf=node.is_leaf)
        mid      = len(node.keys) // 2

        if node.is_leaf:
            new_node.keys   = node.keys[mid:]
            new_node.values = node.values[mid:]
            node.keys       = node.keys[:mid]
            node.values     = node.values[:mid]
            new_node.next   = node.next
            node.next       = new_node
            parent.keys.insert(index, new_node.keys[0])
            parent.children.insert(index + 1, new_node)
        else:
            mid_key          = node.keys[mid]
            new_node.keys    = node.keys[mid + 1:]
            new_node.children= node.children[mid + 1:]
            node.keys        = node.keys[:mid]
            node.children    = node.children[:mid + 1]
            parent.keys.insert(index, mid_key)
            parent.children.insert(index + 1, new_node)

    def delete(self, key):
        self._delete(self.root, key)
        if not self.root.is_leaf and len(self.root.keys) == 0:
            self.root = self.root.children[0]

    def _delete(self, node, key):
        if node.is_leaf:
            if key in node.keys:
                idx = node.keys.index(key)
                node.keys.pop(idx)
                node.values.pop(idx)
            return

        idx = 0
        while idx < len(node.keys) and key >= node.keys[idx]:
            idx += 1
        child = node.children[idx]
        self._delete(child, key)

        min_keys = math.ceil((self.order - 1) / 2)
        if len(child.keys) < min_keys:
            self._fill_child(node, idx)

        if not node.is_leaf:
            for i in range(len(node.children) - 1):
                if node.children[i + 1].keys:
                    node.keys[i] = node.children[i + 1].keys[0]

    def _fill_child(self, node, idx):
        min_keys = math.ceil((self.order - 1) / 2)
        if idx > 0 and len(node.children[idx - 1].keys) > min_keys:
            self._borrow_from_prev(node, idx)
        elif idx < len(node.children) - 1 and len(node.children[idx + 1].keys) > min_keys:
            self._borrow_from_next(node, idx)
        else:
            if idx < len(node.children) - 1:
                self._merge(node, idx)
            else:
                self._merge(node, idx - 1)

    def _borrow_from_prev(self, node, idx):
        child   = node.children[idx]
        sibling = node.children[idx - 1]
        if child.is_leaf:
            child.keys.insert(0, sibling.keys.pop())
            child.values.insert(0, sibling.values.pop())
            node.keys[idx - 1] = child.keys[0]
        else:
            child.keys.insert(0, node.keys[idx - 1])
            node.keys[idx - 1] = sibling.keys.pop()
            child.children.insert(0, sibling.children.pop())

    def _borrow_from_next(self, node, idx):
        child   = node.children[idx]
        sibling = node.children[idx + 1]
        if child.is_leaf:
            child.keys.append(sibling.keys.pop(0))
            child.values.append(sibling.values.pop(0))
            if sibling.keys:
                node.keys[idx] = sibling.keys[0]
        else:
            child.keys.append(node.keys[idx])
            node.keys[idx] = sibling.keys.pop(0)
            child.children.append(sibling.children.pop(0))

    def _merge(self, node, idx):
        child   = node.children[idx]
        sibling = node.children[idx + 1]
        if child.is_leaf:
            child.keys.extend(sibling.keys)
            child.values.extend(sibling.values)
            child.next = sibling.next
        else:
            child.keys.append(node.keys[idx])
            child.keys.extend(sibling.keys)
            child.children.extend(sibling.children)
        node.keys.pop(idx)
        node.children.pop(idx + 1)

    def update(self, key, new_value):
        node = self.root
        while not node.is_leaf:
            for i, k in enumerate(node.keys):
                if key < k:
                    node = node.children[i]
                    break
            else:
                node = node.children[-1]
        for i, k in enumerate(node.keys):
            if k == key:
                node.values[i] = new_value
                return True
        return False

    def range_query(self, start_key, end_key):
        node = self.root
        while not node.is_leaf:
            for i, k in enumerate(node.keys):
                if start_key < k:
                    node = node.children[i]
                    break
            else:
                node = node.children[-1]
        result = []
        while node:
            for i, key in enumerate(node.keys):
                if start_key <= key <= end_key:
                    result.append((key, node.values[i]))
                elif key > end_key:
                    return result
            node = node.next
        return result

    def get_all(self):
        node = self.root
        while not node.is_leaf:
            node = node.children[0]
        result = []
        while node:
            for i in range(len(node.keys)):
                result.append((node.keys[i], node.values[i]))
            node = node.next
        return result

    def _get_all(self, node, result):
        if node.is_leaf:
            for i in range(len(node.keys)):
                result.append((node.keys[i], node.values[i]))
        else:
            for child in node.children:
                self._get_all(child, result)

    def visualize_tree(self, filename=None):
        if Digraph is None:
            raise ImportError(
                "graphviz is required for visualize_tree(); "
                "install it to generate B+ tree diagrams."
            )
        dot = Digraph()
        self._add_nodes(dot, self.root)
        self._add_edges(dot, self.root)

        if filename:
            dot.render(filename, format='png')
        return dot

    def _add_nodes(self, dot, node):
        node_id = str(id(node))
        label = "|".join(map(str, node.keys))
        dot.node(node_id, label)

        if not node.is_leaf:
            for child in node.children:
                self._add_nodes(dot, child)

    def _add_edges(self, dot, node):
        if not node.is_leaf:
            for child in node.children:
                dot.edge(str(id(node)), str(id(child)))
                self._add_edges(dot, child)
