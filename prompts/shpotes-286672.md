# Gemini 4 Argon video by @shpotes

[Original post](https://x.com/shpotes/status/2110222482632286672)

- **Category:** Games & interactive
- **Built with:** Canvas
- **Author:** [@shpotes](https://x.com/shpotes)

## Prompt

```text
Build "Gummy Bears" - a single self-contained HTML file (three.js from a CDN is the only dependency): a handful of translucent gummy bears on a white table that you can grab, stretch, squash, throw and pour.

The bears
- Classic gummy bear silhouette: round head with two ears, short snout, plump body, stubby arms and legs, tiny molded eyes and nose
- Every part melts smoothly into the next - build the body as an implicit surface (metaballs / marching cubes), not separate spheres
- Material: real gummy candy. Translucent with transmission and refraction, colored light absorption that gets deeper in thick parts, glossy clearcoat with sharp highlights
- Colors: cherry red, orange, lemon yellow, apple green, clear pineapple
- Soft colored shadow under each bear, tinted by the bear's own color

Physics (this is the whole point - it must feel like jelly, not plastic)
- Each bear is a soft body: mass points for head, ears, snout, body, belly, hands and feet, held together by volume-preserving shape matching
- Limbs and neck are rendered as stretchy strands between points, getting thinner as they stretch
- Grab any part and pull: it stretches like rubber, the rest of the bear leans after it, on release it snaps back with a damped wobble
- Pull the head up: the neck stretches, the body follows, on release the bear squashes and hops
- Press down on the head: the bear pancakes, bulges sideways, then launches itself back up
- Throw a bear: it flies, squashes on landing, bounces and pushes other bears out of the way
- Bears collide with each other and never pass through one another
- Idle bears do small random hops with squash and stretch
- "Pour more bears" drops a handful from above into a wobbling, jiggling pile

UI
- Editorial product-page style on a white background. Large italic serif title "Gummy / Bears.", a short subtitle, a minimal card on the right with flavor swatches, a wobble slider, live "Stretch" and "Bounces" readouts and a "Pour more bears" button
- A subtle circular cursor that grows while grabbing
- ACES tone mapping, environment reflections, soft key and back light. Smooth 60fps
```
