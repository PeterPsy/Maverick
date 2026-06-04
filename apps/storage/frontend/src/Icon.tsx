import type { ReactNode, SVGProps } from 'react';

type IconProps = Omit<SVGProps<SVGSVGElement>, 'name'> & {
  name: string;
};

const paths: Record<string, ReactNode> = {
  add: <path d="M12 5v14M5 12h14" />,
  article: <path d="M7 3h7l4 4v14H7zM14 3v5h5M9 12h6M9 16h6" />,
  audio_file: <path d="M8 4h7l3 3v13H8zM15 4v4h4M10 16a2 2 0 1 0 4 0V9h3M14 11h3" />,
  auto_awesome: <path d="m12 3 1.4 4.2L18 9l-4.6 1.8L12 15l-1.4-4.2L6 9l4.6-1.8zM5 15l.7 2.1L8 18l-2.3.9L5 21l-.7-2.1L2 18l2.3-.9zM19 14l.8 2.4L22 17l-2.2.6L19 20l-.8-2.4L16 17l2.2-.6z" />,
  category: <path d="M5 5h6v6H5zM14 5h5v5h-5zM5 14h5v5H5zM14 14h5v5h-5z" />,
  check: <path d="m5 12 4 4 10-10" />,
  check_circle: <path d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  cloud_upload: <path d="M16 17h2.2a3.8 3.8 0 0 0 .4-7.6 6 6 0 0 0-11.4-1.7A4.8 4.8 0 0 0 6 17h2M12 18V10M8.8 13.2 12 10l3.2 3.2" />,
  content_copy: <path d="M8 8h10v12H8zM6 16H5a1 1 0 0 1-1-1V5h10v1" />,
  create_new_folder: <path d="M3 7h6l2 2h10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM16 11v6M13 14h6" />,
  database: <path d="M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3ZM5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />,
  delete: <path d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3" />,
  description: <path d="M7 3h7l4 4v14H7zM14 3v5h5M9 13h6M9 17h4" />,
  download: <path d="M12 3v11M8 10l4 4 4-4M5 19h14" />,
  draft: <path d="M7 3h7l4 4v14H7zM14 3v5h5" />,
  edit: <path d="M5 19h4l10-10-4-4L5 15zM14 6l4 4" />,
  error: <path d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 7v6M12 17h.01" />,
  filter_list: <path d="M4 6h16M7 12h10M10 18h4" />,
  folder: <path d="M3 7h6l2 2h10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
  folder_managed: <path d="M3 7h6l2 2h10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM14 14l2 2 4-4" />,
  fullscreen: <path d="M8 3H3v5M3 3l7 7M16 3h5v5M21 3l-7 7M8 21H3v-5M3 21l7-7M16 21h5v-5M21 21l-7-7" />,
  fullscreen_exit: <path d="M10 4v6H4M4 10l6-6M14 4v6h6M20 10l-6-6M10 20v-6H4M4 14l6 6M14 20v-6h6M20 14l-6 6" />,
  grid_view: <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" />,
  home_storage: <path d="m3 11 9-8 9 8M5 10v10h14V10M9 20v-6h6v6" />,
  image: <path d="M4 5h16v14H4zM8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM4 16l4-4 3 3 3-4 6 6" />,
  info: <path d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 11v6M12 7h.01" />,
  markdown: <path d="M3 6h18v12H3zM6 15V9l3 3 3-3v6M16 9v6M14 13l2 2 2-2" />,
  movie: <path d="M4 5h16v14H4zM8 5v14M16 5v14M4 9h4M16 9h4M4 15h4M16 15h4" />,
  open_in_new: <path d="M14 4h6v6M13 11l7-7M20 14v6H4V4h6" />,
  picture_as_pdf: <path d="M7 3h7l4 4v14H7zM14 3v5h5M9 16v-4h2a1.5 1.5 0 0 1 0 3H9M13 16v-4h1.5a2 2 0 0 1 0 4H13M17 16v-4h3" />,
  progress_activity: <path d="M21 12a9 9 0 0 1-9 9M3 12a9 9 0 0 1 9-9M18.4 5.6A9 9 0 0 1 21 12M5.6 18.4A9 9 0 0 1 3 12" />,
  refresh: <path d="M20 6v5h-5M4 18v-5h5M18 11a6.5 6.5 0 0 0-11.2-4.5L4 9M6 13a6.5 6.5 0 0 0 11.2 4.5L20 15" />,
  save: <path d="M5 4h12l2 2v14H5zM8 4v6h8V4M8 20v-6h8v6" />,
  search: <path d="m20 20-4.5-4.5M18 11a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z" />,
  slideshow: <path d="M4 5h16v12H4zM10 9l5 2-5 2zM8 21h8" />,
  sort: <path d="M7 4v14M4 15l3 3 3-3M17 20V6M14 9l3-3 3 3" />,
  table: <path d="M4 5h16v14H4zM4 10h16M4 15h16M10 5v14M15 5v14" />,
  upload_file: <path d="M7 3h7l4 4v14H7zM14 3v5h5M12 18v-7M9 14l3-3 3 3" />,
  view_list: <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />
};

export function Icon({ name, className = '', ...props }: IconProps) {
  return (
    <svg
      {...props}
      className={`storage-icon ${className}`.trim()}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={props['aria-hidden'] ?? true}
    >
      {paths[name] || paths.draft}
    </svg>
  );
}
