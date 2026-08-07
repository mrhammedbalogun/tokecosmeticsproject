/** One row of the media library (`/admin/media/`), as the API serialises it. */
export interface MediaAssetRow {
  id: number;
  /** Absolute URL to the file — CloudFront in prod, Django /media in dev. */
  file: string;
  kind: "image" | "video";
  original_name: string;
  size: number;
  created_at: string;
}
