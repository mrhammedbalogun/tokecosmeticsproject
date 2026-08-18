/** The reviews section exists to do two things: show REAL reviews, and send a click
 * to that exact review on Google. Both are easy to break silently (a card that stops
 * being a link still looks fine), so they are pinned here. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GoogleReviews } from "../GoogleReviews";

const PERMALINK =
  "https://www.google.com/maps/reviews/data=!4m6!14m5!1m4!2m3!1sChdDSUhN!2m1!1s0x103bec48d2395e8f:0xe75fd548677a8d84";

const reviews = {
  rating: "4.6",
  count_text: "49",
  profile_url: "https://search.google.com/local/writereview?placeid=ChIJj1450kjsOxARhI16Z0jVX-c",
  items: [
    {
      id: 1,
      author: "raira M",
      location: "",
      rating: 5,
      text: "I barely have acne anymore.",
      review_url: PERMALINK,
      reviewed_at_text: "",
      sort: 0,
    },
  ],
};

describe("GoogleReviews", () => {
  it("links each card to that review's own permalink, in a new tab", () => {
    render(<GoogleReviews reviews={reviews} />);
    const card = screen.getByRole("link", { name: /raira M/ });
    expect(card).toHaveAttribute("href", PERMALINK);
    expect(card).toHaveAttribute("target", "_blank");
    // Opening a Google tab from our page without this leaks window.opener.
    expect(card).toHaveAttribute("rel", "noreferrer");
  });

  it("sends 'Review us on Google' to the write-a-review dialog", () => {
    render(<GoogleReviews reviews={reviews} />);
    expect(screen.getByRole("link", { name: /review us on google/i })).toHaveAttribute(
      "href",
      reviews.profile_url,
    );
  });

  it("renders nothing at all rather than an empty section", () => {
    const { container } = render(<GoogleReviews reviews={{ ...reviews, items: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });
  it("widens to 5-up so the fifth card does not orphan a row", () => {
    const five = {
      ...reviews,
      items: Array.from({ length: 5 }, (_, i) => ({ ...reviews.items[0], id: i + 1 })),
    };
    const { container } = render(<GoogleReviews reviews={five} />);
    expect(container.querySelector(".lg\\:grid-cols-5")).not.toBeNull();
    // ...and stays 4-up at the count the grid was designed for.
    const { container: four } = render(
      <GoogleReviews reviews={{ ...reviews, items: five.items.slice(0, 4) }} />,
    );
    expect(four.querySelector(".lg\\:grid-cols-4")).not.toBeNull();
  });
});
