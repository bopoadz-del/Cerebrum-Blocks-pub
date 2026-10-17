"""Console Floor pack — product-side console router.

Serves the ONE console UI at `/`, exposes capability discovery at
`/v1/capabilities`, and executes the product's formulas capability at
`/v1/pack/formulas`. Every answer from the formulas path carries an
authority label (grounding verdict + source), so an operator can see which
layer produced the answer.
"""
