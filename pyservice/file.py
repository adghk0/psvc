import os

def mkdir(path):
    path = os.path.abspath(path)
    p = os.path.dirname(path)
    if not (os.path.exists(p) and os.path.isdir(p)):
        mkdir(p)
    if not os.path.exists(path):
        os.mkdir(path)

def ps_path(service, *path):
    result = ''
    if len(path) > 1:
        result = ps_path(service, os.path.join(path[0], *path[1:]))
    elif len(path) == 1:
        path = path[0]
        if path.startswith('.'):
            result = os.path.abspath(os.path.join(service.root_path, path))
        else:
            result = os.path.abspath(path)
    return result

def copy(origin, destination):
    pass
