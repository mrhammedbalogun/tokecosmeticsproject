import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MediaLibraryModal } from "@/components/content/MediaLibraryModal";

const searchMediaAction = vi.fn(async () => ({ items: [], hasMore: false }));
const uploadMediaAction = vi.fn();
const requestVideoTicketAction = vi.fn();
const finalizeVideoAction = vi.fn();

vi.mock("@/app/(shell)/content/media/actions", () => ({
  searchMediaAction: (...args: unknown[]) => searchMediaAction(...(args as [])),
  uploadMediaAction: (...args: unknown[]) => uploadMediaAction(...(args as [])),
  requestVideoTicketAction: (...args: unknown[]) => requestVideoTicketAction(...(args as [])),
  finalizeVideoAction: (...args: unknown[]) => finalizeVideoAction(...(args as [])),
}));

const uploadToS3 = vi.fn();
vi.mock("@/lib/upload", () => ({
  uploadToS3: (...args: unknown[]) => uploadToS3(...(args as [])),
}));

function chooseVideo(size: number, name = "film.mp4") {
  const input = screen.getByLabelText(/upload/i, { selector: "input[type=file]" });
  const file = new File(["x"], name, { type: "video/mp4" });
  Object.defineProperty(file, "size", { value: size });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
  return file;
}

beforeEach(() => {
  vi.clearAllMocks();
  searchMediaAction.mockResolvedValue({ items: [], hasMore: false });
});

describe("MediaLibraryModal video uploads", () => {
  it("refuses a video over the ceiling without contacting the server", async () => {
    render(
      <MediaLibraryModal kind="video" heading="Video" onPick={() => {}} onClose={() => {}} />,
    );

    chooseVideo(200_000_000);

    expect(await screen.findByRole("alert")).toHaveTextContent(/200\.0 MB/);
    expect(requestVideoTicketAction).not.toHaveBeenCalled();
    expect(uploadToS3).not.toHaveBeenCalled();
  });

  it("shows upload progress and finalizes on success", async () => {
    const onPick = vi.fn();
    const ticket = { url: "https://s3.example", fields: {}, key: "incoming/a.mp4" };
    requestVideoTicketAction.mockResolvedValue({ ticket });
    let reportProgress: (pct: number) => void = () => {};
    let finishUpload: () => void = () => {};
    uploadToS3.mockImplementation((_t: unknown, _f: unknown, onProgress: (p: number) => void) => {
      reportProgress = onProgress;
      return {
        promise: new Promise<void>((resolve) => { finishUpload = resolve; }),
        abort: () => {},
      };
    });
    finalizeVideoAction.mockResolvedValue({ asset: { id: 7, kind: "video", file: "x" } });

    render(
      <MediaLibraryModal kind="video" heading="Video" onPick={onPick} onClose={() => {}} />,
    );
    chooseVideo(10_000_000);

    await waitFor(() => expect(uploadToS3).toHaveBeenCalled());
    reportProgress(42);
    expect(await screen.findByText(/42%/)).toBeInTheDocument();

    finishUpload();
    await waitFor(() => expect(finalizeVideoAction).toHaveBeenCalledWith({
      key: "incoming/a.mp4",
      originalName: "film.mp4",
    }));
    await waitFor(() => expect(onPick).toHaveBeenCalledWith({ id: 7, kind: "video", file: "x" }));
  });

  it("surfaces a failed finalize instead of picking anything", async () => {
    const onPick = vi.fn();
    requestVideoTicketAction.mockResolvedValue({
      ticket: { url: "u", fields: {}, key: "incoming/a.mp4" },
    });
    uploadToS3.mockReturnValue({ promise: Promise.resolve(), abort: () => {} });
    finalizeVideoAction.mockResolvedValue({ message: "That file isn't an mp4 or webm video." });

    render(
      <MediaLibraryModal kind="video" heading="Video" onPick={onPick} onClose={() => {}} />,
    );
    chooseVideo(10_000_000);

    expect(await screen.findByRole("alert")).toHaveTextContent(/isn't an mp4/);
    expect(onPick).not.toHaveBeenCalled();
  });
});
