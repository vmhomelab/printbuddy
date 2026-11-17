import { useLayoutEffect, useState } from 'react';

/**
 * False until the component's first render has been committed to the page.
 *
 * For a camera stream <img>: give it its src only once this is true. React
 * creates an element and sets its attributes while rendering, before the
 * commit, and React 19 renders trees it then throws away (a Suspense retry,
 * prerendering the siblings of a suspended tree). An <img> rendered with an
 * MJPEG src opens the stream at once, and a thrown-away one keeps it open with
 * no ref cleanup or effect to close it or send /camera/stop. Each new attempt
 * also starts from fresh state (a new viewer id), so the backend saw a dozen
 * viewers for one opened camera, all pulling every frame.
 *
 * Flipped in a layout effect: the src is set in the same frame as the commit,
 * before the browser paints.
 */
export function useCommitted(): boolean {
  const [committed, setCommitted] = useState(false);
  useLayoutEffect(() => {
    setCommitted(true);
  }, []);
  return committed;
}
