"""Generate fixed cases with a constructive solution for every difficulty."""
import random
from design import HERE, LEVELS, dump, score

WORDS = """
sand sail shell silk silver scent stone steam stream spark sketch sky snow spring sunset
swan surf sound slope seed soft shade stage shelf screen scene still scroll song story
clay cloud cliff coast cedar chalk chart cinema color craft cloth crown creek crystal
copper canvas circle calm cave coast curl curve cane clue clear clock cube cup cool
paper paint path pine pond plume petal pearl prism print patch panel peak peach pink
plant plain plate plaque plot porch pylon polish pitch plum pulp pulse pump plume
bay bark bird branch brick bridge brook bloom brush breeze brass beam bead berry
blue black brown bronze block belt bench board bowl book box bun bulb bit boot
glass gloss grove grass grain grape glow glade globe glyph gold gray green ground
gravel grip grid guest guild gate gallery garden garland guide gust gulf gum gear
map mask marsh moss moon mist mirror mural metal marble marker mat mint maze
museum music muse model module mold monument mount mound mud mulch mug musk
table tack trail track trace train tray tree twig tone tint tile tower town tune
tulip turf trunk tube tool torch thread thumb theme theater ticket tide time trim
arch amber angle apple apron axis anchor arrow art atlas autumn avenue acre
field fern flame fleece flow flower foam fold form frame frost fruit fern fin
light lamp lake leaf linen line link lime lily loop lens loom lint letter
rose reed reed reef reed reed reed river ridge rim ring rail rain rake root rust
dawn dusk dune deck dock door draft drift drop drip drum dust dial dish dye
""".split()


def witness(case, level):
    taken = {line[key] for line in case["lines"] for key in ("first", "last", "anchor")}
    rows = [[None] * level for _ in range(4)]
    for row, rule in zip(rows, case["lines"]):
        row[0], row[-1], row[rule["position"] - 1] = rule["first"], rule["last"], rule["anchor"]
    # Allocate scarce initial letters for all rows before allocating other words.
    for constrained in (True, False):
        for row, rule in zip(rows, case["lines"]):
            needed = LEVELS[level] if constrained else row.count(None)
            choices = [word for word in case["pool"] if word not in taken
                       and rule["forbidden"] not in word
                       and word.startswith(rule["initial"]) == constrained]
            if len(choices) < needed:
                return None
            for word in choices[:needed]:
                row[row.index(None)] = word
                taken.add(word)
    return "\n".join(f"{i}: " + " ".join(row) for i, row in enumerate(rows, 1))


def generate(rng, identifier):
    while True:
        pool = sorted(rng.sample(sorted(set(WORDS)), 108))
        reserved = set()
        lines = []
        for i, initial in enumerate(rng.sample(list("scpbgmt"), 4)):
            forbidden = rng.choice("aeio")
            options = [w for w in pool if w not in reserved and w[0] != initial and forbidden not in w]
            first, last, anchor = rng.sample(options, 3)
            reserved.update((first, last, anchor))
            lines.append(dict(first=first, last=last, anchor=anchor, position=4 + i,
                              initial=initial, forbidden=forbidden))
        case = {"id": identifier, "pool": pool, "lines": lines}
        solutions = {level: witness(case, level) for level in LEVELS}
        if all(solutions.values()):
            assert all(all(score(answer, case, level).values()) for level, answer in solutions.items())
            case["witnesses"] = solutions
            return case


def main():
    rng = random.Random(150451)
    dump(HERE / "cases.json", {
        "pilot": [generate(rng, f"P{i:02}") for i in range(1, 4)],
        "main": [generate(rng, f"Q{i:02}") for i in range(1, 11)],
    })


if __name__ == "__main__":
    main()
