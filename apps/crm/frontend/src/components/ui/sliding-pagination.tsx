import { useEffect, useRef, useState } from 'react';

type PaginationProps = {
  totalPages: number;
  currentPage: number;
  onPageChange: (page: number) => void;
  className?: string;
  maxVisiblePages?: number;
};

export default function SlidingPagination({
  totalPages,
  currentPage,
  onPageChange,
  className = '',
  maxVisiblePages = 7,
}: PaginationProps) {
  const buttonRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [underlineStyle, setUnderlineStyle] = useState({ left: 0, width: 0 });
  const safeTotalPages = Math.max(1, totalPages);
  const safeCurrentPage = Math.min(Math.max(1, currentPage), safeTotalPages);

  useEffect(() => {
    const currentButton = buttonRefs.current[safeCurrentPage - 1];
    if (!currentButton?.parentElement) {
      return;
    }
    const rect = currentButton.getBoundingClientRect();
    const parentRect = currentButton.parentElement.getBoundingClientRect();
    setUnderlineStyle({
      left: rect.left - parentRect.left,
      width: rect.width,
    });
  }, [safeCurrentPage, safeTotalPages]);

  function generatePages() {
    if (safeTotalPages <= maxVisiblePages) {
      return Array.from({ length: safeTotalPages }, (_, index) => index + 1);
    }

    const pages: (number | -1)[] = [];
    const first = 1;
    const last = safeTotalPages;
    const sideCount = 1;
    const middleCount = Math.max(1, maxVisiblePages - 2 * sideCount - 2);

    pages.push(first);

    let left = Math.max(safeCurrentPage - Math.floor(middleCount / 2), sideCount + 1);
    const right = Math.min(safeCurrentPage + Math.floor(middleCount / 2), safeTotalPages - sideCount);

    if (left > sideCount + 1) {
      pages.push(-1);
    } else {
      left = sideCount + 1;
    }

    for (let page = left; page <= right; page += 1) {
      pages.push(page);
    }

    if (right < safeTotalPages - sideCount) {
      pages.push(-1);
    }

    pages.push(last);
    return pages;
  }

  return (
    <div className={`sliding-pagination ${className}`.trim()}>
      {generatePages().map((pageNumber, index) =>
        pageNumber === -1 ? (
          <span key={`dots-${index}`} className="sliding-pagination__dots">...</span>
        ) : (
          <button
            key={pageNumber}
            ref={(element) => {
              buttonRefs.current[pageNumber - 1] = element;
            }}
            type="button"
            onClick={() => onPageChange(pageNumber)}
            className={pageNumber === safeCurrentPage ? 'is-active' : ''}
          >
            {pageNumber}
          </button>
        )
      )}
      <span
        aria-hidden="true"
        className="sliding-pagination__underline"
        style={{ left: underlineStyle.left, width: underlineStyle.width }}
      />
    </div>
  );
}
