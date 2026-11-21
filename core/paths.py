"""Operacje na sciezkach pol typu 'A.b', 'A[].b', 'A[].c[].d'."""


def _split(path: str):
    return path.split(".")


def iter_values(obj, path: str):
    """Zwraca liste (kontener, klucz, wartosc) dla wszystkich dopasowan sciezki."""
    out = []

    def walk(node, parts):
        if not parts or node is None:
            return
        key, rest = parts[0], parts[1:]
        is_list = key.endswith("[]")
        key = key[:-2] if is_list else key
        if not isinstance(node, dict) or key not in node:
            return
        if is_list:
            items = node[key] if isinstance(node[key], list) else []
            for item in items:
                if rest:
                    walk(item, rest)
        elif rest:
            walk(node[key], rest)
        else:
            out.append((node, key, node[key]))

    walk(obj, _split(path))
    return out


def get(obj, path: str):
    """Pierwsza wartosc dla sciezki bez list (lub pierwszego elementu listy)."""
    found = iter_values(obj, path)
    return found[0][2] if found else None


def set_first(obj, path: str, value):
    """Ustawia wartosc; dla 'A[].b' w pierwszym elemencie (tworzy go, jesli trzeba)."""
    node = obj
    parts = _split(path)
    for i, key in enumerate(parts):
        last = i == len(parts) - 1
        is_list = key.endswith("[]")
        key = key[:-2] if is_list else key
        if last:
            node[key] = value
            return
        if is_list:
            lst = node.setdefault(key, [])
            if not lst:
                lst.append({})
            node = lst[0]
        else:
            node = node.setdefault(key, {})
