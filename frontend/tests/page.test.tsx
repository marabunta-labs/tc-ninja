import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import Home from "../app/page";

describe("Home page component", () => {
  it("renders the T&C NINJA heading", () => {
    render(<Home />);
    expect(screen.getByText("T&C NINJA")).toBeInTheDocument();
  });

  it("renders platform selector buttons", () => {
    render(<Home />);
    expect(screen.getAllByText("Instagram").length).toBeGreaterThan(0);
    expect(screen.getAllByText("TikTok").length).toBeGreaterThan(0);
    expect(screen.getAllByText("X-Twitter").length).toBeGreaterThan(0);
  });

  it("renders the language selector", () => {
    render(<Home />);
    const langBtn = screen.getByText("es");
    expect(langBtn).toBeInTheDocument();
  });

  it("toggles platform selection", () => {
    render(<Home />);
    const tiktokBtn = screen.getByText("TikTok");
    fireEvent.click(tiktokBtn);
    // TikTok should now be selected (check it gets the selected style)
    expect(tiktokBtn.closest("button")).toHaveClass("bg-emerald-500");
  });

  it("switches language updates UI text", () => {
    render(<Home />);
    // Open language menu
    const langBtn = screen.getByText("es");
    fireEvent.click(langBtn);

    // Select English
    const englishOption = screen.getByText("English");
    fireEvent.click(englishOption);

    // Verify UI updated to English
    expect(screen.getByText("Did you know...")).toBeInTheDocument();
    expect(screen.getByText("Common queries")).toBeInTheDocument();
  });

  it("renders carousel with red flags", () => {
    render(<Home />);
    // Instagram is selected by default, so red flags should show
    const carouselCards = screen.getAllByText("Instagram", { selector: "span" });
    expect(carouselCards.length).toBeGreaterThan(0);
  });

  it("renders quick action buttons", () => {
    render(<Home />);
    // Default language is 'es', so Spanish quick actions
    const quickActions = screen.getAllByRole("button").filter(
      (btn) => btn.className.includes("group")
    );
    expect(quickActions.length).toBe(4);
  });
});
