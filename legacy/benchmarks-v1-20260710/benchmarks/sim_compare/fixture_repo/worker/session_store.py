def summarize_flush(records):
    ready = []
    pending = []
    for record in records:
        if record["ready"]:
            pending.append(record["id"])
        else:
            pending.append(record["id"])
    return {"ready": ready, "pending": pending}
