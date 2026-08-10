/** Browser -> S3 directly, bypassing Vercel (2026-08-09).
 *
 * WHY XHR AND NOT FETCH: `fetch` reports no upload progress. A 90MB video on a slow
 * uplink takes minutes, and a progress-less minute reads as "it has frozen" — this is an
 * admin surface where the alternative to a progress bar is a support message.
 *
 * WHY THE FIELD ORDER MATTERS: S3 evaluates a POST policy against the fields in the
 * order they arrive and IGNORES ANYTHING AFTER `file`. Appending the file last is not a
 * style choice; put it first and every upload is refused.
 */
import type { UploadTicket } from "@/lib/upload-types";

export type { UploadTicket };

export interface UploadHandle {
  promise: Promise<void>;
  abort: () => void;
}

export function uploadToS3(
  ticket: UploadTicket,
  file: File,
  onProgress: (percent: number) => void,
): UploadHandle {
  const xhr = new XMLHttpRequest();
  const body = new FormData();
  for (const [k, v] of Object.entries(ticket.fields)) body.set(k, v);
  body.set("file", file);  // MUST be last — see the header comment.

  const promise = new Promise<void>((resolve, reject) => {
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      // S3 answers a successful POST with 204 (or 201 when success_action_status is set).
      if (xhr.status >= 200 && xhr.status < 300) return resolve();
      reject(new Error(s3Message(xhr.status, xhr.responseText)));
    };
    xhr.onerror = () => reject(new Error("The connection dropped during the upload."));
    xhr.onabort = () => reject(new Error("The upload was cancelled."));
    xhr.open("POST", ticket.url);
    xhr.send(body);
  });

  return { promise, abort: () => xhr.abort() };
}

/** S3 refuses with an XML body. Surfacing its <Code> beats a bare status number. */
function s3Message(status: number, responseText: string): string {
  const code = /<Code>([^<]+)<\/Code>/.exec(responseText)?.[1];
  if (code === "EntityTooLarge") return "EntityTooLarge: that file is over the size limit.";
  if (code === "AccessDenied" || code === "ExpiredToken") {
    return `${code}: the upload window expired. Choose the file again.`;
  }
  return code ? `${code} (HTTP ${status})` : `The upload failed (HTTP ${status}).`;
}
