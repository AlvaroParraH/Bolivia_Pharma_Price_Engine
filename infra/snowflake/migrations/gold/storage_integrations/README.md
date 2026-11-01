# Gold storage integration migrations

Place reviewed SQL changes for storage integrations used by Gold external
stages here. Storage integrations are account-level objects, not schema objects;
this folder groups them by their intended use. Gold is a planned schema.

Keep a shared integration's definition in one location rather than duplicating
it across layers. No migration runner or execution order is configured yet.
