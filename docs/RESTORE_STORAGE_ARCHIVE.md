# Prepare attachment evidence for a restore drill

Use the independent Storage backup selected for the drill. A database backup covers object metadata. The matching private object bytes must come from a separate backup. Keep the bucket catalogue, archive and manifest in a private directory outside the repository. Retain the final manifest digest separately with the backup receipt.

1. At the selected recovery point, run the read-only catalogue query on a database snapshot of that point, or on the source while Storage writes are frozen across both backups and captures. Use the backup owner's verified database connection and its password file. The query captures all paths and expected sizes in the two original private buckets and the version bucket if it existed. A failed query leaves the inventory unverified.

   ```bash
   umask 077
   psql -XqAtw -v ON_ERROR_STOP=1 -v source_ref="$SOURCE_REF" -v backup_id="$RECOVERY_POINT" \
     -f scripts/restore_storage_catalogue.sql > "$PRIVATE_DIR/catalogue.json"
   ```

2. Mount or extract the independently archived original object bytes read-only as `$ARCHIVE/<bucket>/<exact object key>`. Represent an existing empty bucket by its empty directory. Retain content types and other object metadata from the original storage provider's backup. Generate a private manifest and record the SHA-256 printed on success.

   ```bash
   python -m scripts.restore_storage_manifest --catalogue "$PRIVATE_DIR/catalogue.json" \
     --archive "$ARCHIVE" --source-environment "$SOURCE_REF" --source-backup-id "$RECOVERY_POINT" \
     --out "$PRIVATE_DIR/storage-inventory.json"
   ```

   The generator compares exact keys and sizes in each bucket and streams every regular file through SHA-256. It rejects extra or missing objects, symbolic links, missing sizes, public buckets and a version-bucket presence mismatch. The source catalogue must agree even when the archive has no objects.

3. In the isolated scratch project, restore the original bucket configuration and its private access settings. Use the Storage dashboard in the scratch project, or the backup provider's restore-to-new-target operation, to upload the archived bytes under the exact bucket and key from the manifest and restore their metadata. For the dashboard, choose the bucket and key's parent folder and upload the file using its original basename. Preserve folder nesting. If restored database metadata already occupies a key or an upload reports a conflict, stop and use the provider's scratch-only object-restore procedure. Check the dashboard project ref against the drill's scratch ref before any upload. A historical absent version bucket must also be absent on scratch.

4. Run the normal drill with `--attachment-manifest` pointing at this manifest and `--attachment-manifest-sha256` set to its separate receipt. The drill reads scratch back over Storage, enumerates the objects and verifies their actual bytes. An archive recovered without an independent source catalogue, or a changed source after the backup, cannot establish what was present at the recovery point.
