# Prepare attachment evidence for a restore drill

Use the independent Storage backup selected for the drill. A database backup covers object metadata. The matching private object bytes must come from a separate backup. Keep the bucket catalogue, archive and manifest in a private directory outside the repository. Retain the final manifest digest separately with the backup receipt.

1. At the selected recovery point, run the source capture against the named project while writes are frozen across the database backup, object backup and capture. The one read-only SQL statement observes exact table counts and the private Storage catalogue at the same snapshot. The command selects its verified TLS endpoint from the source project ref. It writes a public-safe summary and a separate owner-only catalogue of object keys and sizes. Retain the SHA-256 of `source-schema.json` independently with the recovery point. The summary's `storage_catalogue_sha256` pins the private catalogue.

   ```bash
   umask 077
   PGPASSFILE="$SOURCE_PGPASSFILE" PGSSLROOTCERT="$SOURCE_PGSSLROOTCERT" \
     python -m scripts.restore_schema_evidence --project-ref "$SOURCE_REF" --source-backup-id "$RECOVERY_POINT" \
       --out "$PRIVATE_DIR/source-schema.json" --storage-catalogue-out "$PRIVATE_DIR/catalogue.json"
   ```

   If the capture or receipt predates the backup's freeze, use a new verified recovery point. Re-enumerating scratch cannot establish the source inventory. Keep both new output paths unused before capture.

2. Mount or extract the independently archived original object bytes read-only as `$ARCHIVE/<bucket>/<exact object key>`. Represent an existing empty bucket by its empty directory. Retain content types and other object metadata from the original storage provider's backup. Generate a private manifest and record the SHA-256 printed on success.

   ```bash
   python -m scripts.restore_storage_manifest --catalogue "$PRIVATE_DIR/catalogue.json" \
     --catalogue-sha256 "$PINNED_STORAGE_CATALOGUE_SHA256" --archive "$ARCHIVE" --source-environment "$SOURCE_REF" --source-backup-id "$RECOVERY_POINT" \
     --out "$PRIVATE_DIR/storage-inventory.json"
   ```

   The generator compares exact keys and sizes in each bucket and streams every regular file through SHA-256. It rejects extra or missing objects, symbolic links, missing sizes, public buckets and a version-bucket presence mismatch. A second walk detects changes in the key set or file identities during the scan. The archive must be immutable: changing a file after the last check, or a same-length replacement before first capture, cannot be ruled out by enumeration. The source catalogue must agree even when the archive has no objects.

3. In the isolated scratch project, restore the original bucket configuration and its private access settings. Use the Storage dashboard in the scratch project, or the backup provider's restore-to-new-target operation, to upload the archived bytes under the exact bucket and key from the manifest and restore their metadata. For the dashboard, choose the bucket and key's parent folder and upload the file using its original basename. Preserve folder nesting. If restored database metadata already occupies a key or an upload reports a conflict, stop and use the provider's scratch-only object-restore procedure. Check the dashboard project ref against the drill's scratch ref before any upload. A historical absent version bucket must also be absent on scratch.

4. Run the normal drill with `--attachment-manifest` pointing at this manifest and `--attachment-manifest-sha256` set to its separate receipt. The drill reads scratch back over Storage, enumerates the objects and verifies their actual bytes. The release gate also requires the keys and sizes represented by the manifest to match the catalogue digest in the separately pinned source schema receipt. An archive recovered without an independent source catalogue, or a changed source after the backup, cannot establish what was present at the recovery point.
