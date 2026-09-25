-- Applied immediately BEFORE the new migration; exercises actual old data.
INSERT INTO auth.users(id) VALUES ('88000000-0000-4000-8000-000000000001');
INSERT INTO public.resume_renovations(device_id,opportunity_id,doc,base_snapshot,method,warnings,updated_at)
 VALUES('88000000-0000-4000-8000-000000000001','old-current',
 '{"sections":[{"id":"old","bullets":[]}],"resume_sig":"unknown-original"}',
 '{"sections":[],"source":"旧原文🧪"}',NULL,'["original warning"]','2024-01-01T01:02:03.123456Z');
INSERT INTO public.resume_renovation_versions(id,device_id,opportunity_id,doc,created_at)
 VALUES('88000000-0000-4000-8000-000000000099','88000000-0000-4000-8000-000000000001','old-current',
 '{"sections":[],"old":"historic exact"}','2023-01-01T01:02:03.123456Z');
