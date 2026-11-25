export function downloadBlob(file: { filename: string; blob: Blob }): void {
  const url = URL.createObjectURL(file.blob);
  const link = document.createElement('a'); link.href = url; link.download = file.filename;
  document.body.appendChild(link);
  try { link.click(); }
  finally {
    link.remove();
    // Let the browser begin reading the Blob before releasing its URL.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
