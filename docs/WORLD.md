# Objects and abilities

CSK360 knows what characters can do with the things in your scene.

![Objects panel](objects_panel.png)

## Label objects

Open **CSK360 > Objects** and press **Detect Labels**. Every unlabelled mesh gets
a guess from its size:

| Label | Meaning | Detected when |
|---|---|---|
| Walk On | a floor | big (4 m² or more) and at floor level |
| Can Stand On | characters can jump or climb onto its top | top 15 cm to 1.5 m up, at least 30 × 30 cm |
| Obstacle | characters walk around it | taller than 15 cm |
| Liftable | characters can pick it up if strong enough | longest side 1.2 m or less |
| Weight | kg, used for lifting | bounding box volume × 150 kg/m³ |

Detected labels say *Detected: check these*. Change anything that's wrong, or
press **Looks Right**; either way the labels become yours and detection never
changes them again (unless you tick *Redo* in Detect Labels).

## Character abilities

Each cast member has abilities in the Cast panel:

* **Weight (kg)**: how heavy they are when someone lifts them (default 60)
* **Can Lift (kg)**: the heaviest thing they can lift alone (default 25)
* **Jump Height**: the highest surface they can jump onto (default 0.5 m)

Select an object and the Objects panel shows **Lift** and **Jump On** buttons for
each character. They answer in plain English, for example
*"Leo can't lift Crate: it weighs 40 kg and Leo can lift 25 kg (15 kg short)."*
Characters can lift together: their strengths add up.

## In scene scripts

```yaml
cast:
  leo:  {character: leo, strength: 40, jump: 0.6, weight: 70}
objects:
  Crate: {liftable: true, weight: 12, jump_onto: true}
```

Pick up, carry, jump onto and spawn come next (see TODO.md) and will use these checks.
