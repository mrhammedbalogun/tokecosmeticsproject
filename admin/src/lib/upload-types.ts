/** The shape the API's video-ticket endpoint returns. */
export interface UploadTicket {
  url: string;
  fields: Record<string, string>;
  key: string;
}
