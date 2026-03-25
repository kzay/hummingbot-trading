## ADDED Requirements

### Requirement: MlFeatureEvent includes resolution field

`MlFeatureEvent` in `platform_lib/contracts/event_schemas.py` SHALL include a `resolution` field of type `str` with default `"1m"`.

#### Scenario: Event serialized with resolution

- **WHEN** an MlFeatureEvent is created with `resolution="15m"`
- **THEN** the serialized payload includes `"resolution": "15m"`

#### Scenario: Existing events default to 1m

- **WHEN** an MlFeatureEvent is deserialized from a payload without a `resolution` field
- **THEN** `resolution` defaults to `"1m"` (backward compatible)

### Requirement: ML Feature Service publishes at multiple resolutions

The ML Feature Service SHALL accept a `ML_PUBLISH_RESOLUTIONS` environment variable (comma-separated, default `"1m"`). For each configured resolution, the service SHALL publish an `MlFeatureEvent` on the bar close of that resolution. The `resolution` field on each event SHALL match the publishing resolution.

#### Scenario: Publish at 1m and 15m

- **WHEN** `ML_PUBLISH_RESOLUTIONS=1m,15m` and the 15th 1m bar completes
- **THEN** two events are published: one with `resolution="1m"` (as usual) and one with `resolution="15m"` containing features computed with the 15m bar as the latest complete bar

#### Scenario: Publish at 1m only (default)

- **WHEN** `ML_PUBLISH_RESOLUTIONS` is not set
- **THEN** only 1m events are published on each 1m bar close (unchanged behavior)

#### Scenario: 15m event not published on non-bar-close minutes

- **WHEN** `ML_PUBLISH_RESOLUTIONS=1m,15m` and the 7th 1m bar completes (not a 15m boundary)
- **THEN** only the 1m event is published; no 15m event is published

### Requirement: Signal consumer maps numeric regime labels to spec names

`_consume_ml_features` SHALL map numeric regime class predictions from `research.py` models to regime spec name strings before calling `set_ml_regime`. The mapping SHALL handle both numeric (int/digit string from vol bucket classifiers: 0=low, 1=normal, 2=elevated, 3=extreme) and string (from ROAD-10 classifiers: `neutral_low_vol`, etc.) regime classes. String regime classes SHALL be passed through unchanged.

#### Scenario: Numeric vol bucket class mapped to regime name

- **WHEN** ML prediction contains `{"regime": {"class": 0, "confidence": 0.7}}`
- **THEN** the regime override is applied as `"neutral_low_vol"` (not `"0"`)

#### Scenario: String regime class passed through

- **WHEN** ML prediction contains `{"regime": {"class": "up", "confidence": 0.8}}`
- **THEN** the regime override is applied as `"up"` unchanged

#### Scenario: Unknown numeric class is skipped

- **WHEN** ML prediction contains `{"regime": {"class": 5, "confidence": 0.9}}`
- **THEN** no regime override is applied; a warning is logged

### Requirement: Signal consumer filters by bot indicator_resolution

`_consume_ml_features` in the signal consumer SHALL compare the event's `resolution` field against the consuming bot's `indicator_resolution` config. Events with mismatched resolution SHALL be skipped.

#### Scenario: Bot7 receives only 15m features

- **WHEN** bot7 has `indicator_resolution: "15m"` and events with both `resolution="1m"` and `resolution="15m"` arrive
- **THEN** only the `resolution="15m"` event is processed; the `resolution="1m"` event is ignored

#### Scenario: Bot1 receives only 1m features

- **WHEN** bot1 has `indicator_resolution: "1m"` (default) and events arrive
- **THEN** only events with `resolution="1m"` (or missing resolution, defaulting to "1m") are processed

#### Scenario: Backward compatibility with events lacking resolution

- **WHEN** an event arrives without a `resolution` field
- **THEN** it is treated as `resolution="1m"` and consumed by bots with `indicator_resolution="1m"`
