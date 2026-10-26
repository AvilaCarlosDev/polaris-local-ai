def generar_reporte(csv_texto):
    l = csv_texto.strip().split("\n")
    h = l[0].split(",")
    t = {}
    c = {}
    tot = 0
    for x in l[1:]:
        if x.strip() == "":
            continue
        p = x.split(",")
        d = dict(zip(h, p))
        v = float(d["cantidad"]) * float(d["precio"])
        if d["vendedor"] in t:
            t[d["vendedor"]] = t[d["vendedor"]] + v
            c[d["vendedor"]] = c[d["vendedor"]] + 1
        else:
            t[d["vendedor"]] = v
            c[d["vendedor"]] = 1
        tot = tot + v
    s = "REPORTE DE VENTAS\n"
    for k in sorted(t, key=lambda k: -t[k]):
        s = s + k + ": " + str(round(t[k], 2)) + " (" + str(c[k]) + " ventas)\n"
    s = s + "TOTAL: " + str(round(tot, 2))
    return s
