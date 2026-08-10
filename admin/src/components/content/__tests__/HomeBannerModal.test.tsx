import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HomeBannerModal } from "@/components/content/HomeBannerModal";
import type { BannerRow, PlacementSpec } from "@/lib/banners";

const saveBannerAction = vi.fn();
const attachBannerMediaAction = vi.fn(async () => ({ savedAt: 1 }));
const clearBannerMediaAction = vi.fn(async () => ({ savedAt: 1 }));
const deleteBannerAction = vi.fn(async () => ({ savedAt: 1 }));
const uploadBannerMediaAction = vi.fn(async () => ({ savedAt: 1 }));

vi.mock("@/app/(shell)/content/banners/actions", () => ({
  saveBannerAction: (...a: unknown[]) => saveBannerAction(...(a as [])),
  attachBannerMediaAction: (...a: unknown[]) => attachBannerMediaAction(...(a as [])),
  clearBannerMediaAction: (...a: unknown[]) => clearBannerMediaAction(...(a as [])),
  deleteBannerAction: (...a: unknown[]) => deleteBannerAction(...(a as [])),
  uploadBannerMediaAction: (...a: unknown[]) => uploadBannerMediaAction(...(a as [])),
}));

const searchMediaAction = vi.fn(async () => ({ items: [], hasMore: false }));
const requestVideoTicketAction = vi.fn();
const finalizeVideoAction = vi.fn();

vi.mock("@/app/(shell)/content/media/actions", () => ({
  searchMediaAction: (...a: unknown[]) => searchMediaAction(...(a as [])),
  uploadMediaAction: vi.fn(),
  requestVideoTicketAction: (...a: unknown[]) => requestVideoTicketAction(...(a as [])),
  finalizeVideoAction: (...a: unknown[]) => finalizeVideoAction(...(a as [])),
}));

const uploadToS3 = vi.fn(() => ({ promise: Promise.resolve(), abort: () => {} }));
vi.mock("@/lib/upload", () => ({
  uploadToS3: (...a: unknown[]) => uploadToS3(...(a as [])),
}));

const SPEC: PlacementSpec = {
  value: "hero",
  label: "Hero",
  guide: "guide",
  aspect: "aspect-video",
  media: true,
  fields: [{ key: "title", label: "Title" }],
} as unknown as PlacementSpec;

function renderModal({ banner = null }: { banner?: BannerRow | null } = {}) {
  return render(
    <HomeBannerModal
      spec={SPEC}
      banner={banner}
      presetSort={0}
      heading="Hero · Slide 1"
      countryOptions={[]}
      onClose={() => {}}
    />,
  );
}

function fileOfSize(size: number, name = "film.mp4"): File {
  const file = new File(["x"], name, { type: "video/mp4" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

function pickVideo(file: File, container: HTMLElement) {
  const input = container.querySelector('input[accept="video/mp4,video/webm"]')!;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

beforeEach(() => {
  vi.clearAllMocks();
  searchMediaAction.mockResolvedValue({ items: [], hasMore: false });
  // jsdom has no object URLs; the modal only needs a string for its preview.
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});

describe("HomeBannerModal video uploads", () => {
  it("keeps PATCHing after a failed video upload — never creates a second banner", async () => {
    // Regression guard for commit 8935354. The video slot is now three steps, which is
    // exactly where a careless edit could reintroduce the duplicate.
    saveBannerAction.mockResolvedValue({ savedAt: 1, id: 42 });
    requestVideoTicketAction.mockResolvedValue({
      ticket: { url: "u", fields: {}, key: "incoming/a.mp4" },
    });
    finalizeVideoAction
      .mockResolvedValueOnce({ message: "verification failed" })
      .mockResolvedValueOnce({ asset: { id: 7, kind: "video", file: "x" } });

    const { container } = renderModal();
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "Hero" } });
    pickVideo(fileOfSize(1_000_000), container);
    await screen.findByText(/applies when you press save/i);

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/verification failed/i);

    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(saveBannerAction).toHaveBeenCalledTimes(2));
    expect(saveBannerAction.mock.calls[1][0].id).toBe(42); // PATCH, not a second POST
    await waitFor(() => expect(attachBannerMediaAction).toHaveBeenCalledWith(42, "video", 7));
  });

  it("saves the chosen playback mode with the banner", async () => {
    saveBannerAction.mockResolvedValue({ savedAt: 1, id: 5 });
    const { container } = renderModal();
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "Hero" } });
    pickVideo(fileOfSize(1_000_000), container);
    await screen.findByRole("radio", { name: /loop/i });

    fireEvent.click(screen.getByRole("radio", { name: /click/i }));
    requestVideoTicketAction.mockResolvedValue({
      ticket: { url: "u", fields: {}, key: "incoming/a.mp4" },
    });
    finalizeVideoAction.mockResolvedValue({ asset: { id: 7 } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(saveBannerAction).toHaveBeenCalled());
    expect(saveBannerAction.mock.calls[0][0].video_mode).toBe("click");
  });

  it("warns about a big LOOPING video and not about a click-to-play one", async () => {
    const { container } = renderModal();
    pickVideo(fileOfSize(9_000_000), container);
    await screen.findByRole("radio", { name: /loop/i });

    fireEvent.click(screen.getByRole("radio", { name: /loop/i }));
    expect(screen.getByRole("status")).toHaveTextContent(/every visitor/i);

    fireEvent.click(screen.getByRole("radio", { name: /click/i }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
