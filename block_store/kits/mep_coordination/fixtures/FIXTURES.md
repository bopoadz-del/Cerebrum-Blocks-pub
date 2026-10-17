# MEP kit fixtures

## schependomlaan_design.ifc — VALID FIXTURE
Source: openBIMstandards/Archive-DataSetSchependomlaan (archived, 66 stars),
`Design model IFC/IFC Schependomlaan.ifc`. 47 MB, schema **IFC2X3**, loads in 5 s.

    IfcFlowSegment              60
    IfcDistributionElement      73
    IfcDistributionFlowElement  60      -> 193 MEP elements
    IfcWall 934  IfcWallStandardCase 282  IfcSlab 279
    IfcBeam 174  IfcColumn 23  IfcCovering 1262  -> 2954 structural
    6 storeys, 3822 products

Real MEP-vs-structure coordination content. Passes the order's fixture test.

## schependomlaan_utilities.ifc — REJECTED, NOT A FIXTURE
`HB_Nutsvoorzieningen.ifc`, 32 MB, but **0 MEP elements, 0 structural, 45
products**. The order's rule is explicit: zero MEP elements in a fixture is
not a fixture. Deleted rather than kept as decoration.

## buildingSMART Simple-Scene — REJECTED for acceptance, kept for unit tests
Building-Hvac 4 elements, Infra-Electrical 2, Infra-Plumbing 24 pipes (one
discipline each, zero clashes). Conformance scenes: usable to prove the parser
does not crash, useless for congestion or top-50 false-positive work.

## CONSTRAINT DISCOVERED — no IfcSystem in the fixture
`IfcSystem` count is **0**. B1 specifies system attribution via
IfcSystem/IfcDistributionSystem relationships; on IFC2X3 models of this vintage
that relationship is absent. System must be derived from entity type and name,
and the derivation must be visible in output so a wrong guess is auditable.

## Owner model — NOT USABLE AS-IS
`Design/BIM/*.nwd` (261 MB and 645 MB) are Navisworks. Parsing .nwd is
FORBIDDEN by this order and by the existing extractor's own guidance. Needs an
IFC export (Navisworks: File > Export > IFC) before the kit can read it.
