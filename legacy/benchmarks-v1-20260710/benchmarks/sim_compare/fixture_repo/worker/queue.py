def drain_ready(items):
    queue = list(items)
    drained = []
    while queue:
        drained.append(queue.pop())
    return drained
