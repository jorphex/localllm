def collect_batches(items, size):
    batches = []
    current = []
    for item in items:
        current.append(item)
        if len(current) == size:
            batches.append(current)
            current = []
    return batches
