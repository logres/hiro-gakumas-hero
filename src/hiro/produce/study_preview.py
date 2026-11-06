"""Read each study choice with single, reversible selection clicks."""


def collect(session, obs, click, wait):
    initial = obs.fields
    choices = initial.get("choices") or []
    indices = [c.get("index") for c in choices]
    if not initial.get("complete") or indices != [0, 1, 2] or type(initial.get("selected")) is not int:
        raise ValueError("授業预览缺少完整选项或确定选中态")
    effects = {}
    current = obs
    for index in indices:
        fields = current.fields
        selected = fields.get("selected")
        if type(selected) is not int or selected not in indices:
            raise ValueError("授業选中态不明，不重复点击")
        session.record(current)
        if selected != index:
            target = next(c for c in fields["choices"] if c["index"] == index)
            center = target.get("center")
            if not center or len(center) != 2:
                raise ValueError("授業选项坐标缺失")
            click(*center)
            wait(.7)
            current = session.observe(scene="STUDY")
        fields = current.fields
        if not fields.get("complete") or fields.get("selected") != index or not fields.get("effect"):
            raise ValueError("授業单击后未确认对应效果，不补点")
        effects[index] = (fields["effect"], current.seq)
    session.record(current)
    merged = dict(current.fields)
    merged["choices"] = [dict(c, effect=effects[c["index"]][0], preview_seq=effects[c["index"]][1])
                         for c in choices]
    for c in merged["choices"]:
        c["selected"] = c["index"] == merged["selected"]
    return session.observe(scene="STUDY", img=session.img, fields=merged)
