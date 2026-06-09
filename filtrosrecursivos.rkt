#lang racket

; filtrosrecursivos.rkt
; Implementación de filtros usando listas inmutables y recursión pura.
;
; Autores: Ivan Burrola, Alberto Lopez, Axel Lugo, Sebastian Viche
; Materia: Implementacion de metodos computacionales

;--------------------------------------------------------------------------------

(provide negative-recursive
         grayscale-recursive
         sepia-recursive
         edge-recursive
         gaussian-recursive)

;; ============================================================
;; UTILIDADES INTERNAS
;; ============================================================

;; Convierte un byte-string ARGB en una lista de píxeles:
;; (list (list a r g b) ...)
(define (bytes->pixel-list buf)
  (define len (bytes-length buf))
  (let loop ([i 0] [acc '()])
    (if (>= i len)
        (reverse acc)
        (loop (+ i 4)
              (cons (list (bytes-ref buf i)
                          (bytes-ref buf (+ i 1))
                          (bytes-ref buf (+ i 2))
                          (bytes-ref buf (+ i 3)))
                    acc)))))

;; Convierte una lista de píxeles de vuelta a un byte-string mutable.
(define (pixel-list->bytes px-list orig-len)
  (define buf (make-bytes orig-len 0))
  (let loop ([lst px-list] [i 0])
    (unless (null? lst)
      (define px (car lst))
      (bytes-set! buf i       (list-ref px 0))
      (bytes-set! buf (+ i 1) (list-ref px 1))
      (bytes-set! buf (+ i 2) (list-ref px 2))
      (bytes-set! buf (+ i 3) (list-ref px 3))
      (loop (cdr lst) (+ i 4))))
  buf)

;; Clamp: mantiene un valor entre 0 y 255.
(define (clamp v) (max 0 (min 255 v)))

;; ============================================================
;; 1. NEGATIVO
;; ============================================================
(define (negative-recursive bytes-buf)
  (define pixels (bytes->pixel-list bytes-buf))
  (define (invert-pixel px)
    (list (list-ref px 0)                        ; alpha: sin cambio
          (- 255 (list-ref px 1))                ; R
          (- 255 (list-ref px 2))                ; G
          (- 255 (list-ref px 3))))              ; B
  (define result (map invert-pixel pixels))
  (pixel-list->bytes result (bytes-length bytes-buf)))

;; ============================================================
;; 2. ESCALA DE GRISES
;; ============================================================
(define (grayscale-recursive bytes-buf)
  (define pixels (bytes->pixel-list bytes-buf))
  (define (gray-pixel px)
    (define r (list-ref px 1))
    (define g (list-ref px 2))
    (define b (list-ref px 3))
    (define lum (exact-round (+ (* 0.299 r) (* 0.587 g) (* 0.114 b))))
    (list (list-ref px 0) lum lum lum))
  (pixel-list->bytes (map gray-pixel pixels) (bytes-length bytes-buf)))

;; ============================================================
;; 3. SEPIA
;; ============================================================
(define (sepia-recursive bytes-buf)
  (define pixels (bytes->pixel-list bytes-buf))
  (define (sepia-pixel px)
    (define r (list-ref px 1))
    (define g (list-ref px 2))
    (define b (list-ref px 3))
    (list (list-ref px 0)
          (clamp (exact-round (+ (* 0.393 r) (* 0.769 g) (* 0.189 b))))
          (clamp (exact-round (+ (* 0.349 r) (* 0.686 g) (* 0.168 b))))
          (clamp (exact-round (+ (* 0.272 r) (* 0.534 g) (* 0.131 b))))))
  (pixel-list->bytes (map sepia-pixel pixels) (bytes-length bytes-buf)))

;; ============================================================
;; HELPER: acceso a píxel en lista 2D (representada como vector de listas)
;; ============================================================

;; Convierte el byte-string en un vector de píxeles para acceso O(1) por índice.
(define (bytes->pixel-vector buf)
  (define n (/ (bytes-length buf) 4))
  (define v (make-vector n #f))
  (for ([i (in-range n)])
    (define base (* i 4))
    (vector-set! v i (list (bytes-ref buf base)
                           (bytes-ref buf (+ base 1))
                           (bytes-ref buf (+ base 2))
                           (bytes-ref buf (+ base 3)))))
  v)

;; Obtiene un canal c del pixel en (x,y) desde un vector.
(define (vec-channel pv x y w c)
  (list-ref (vector-ref pv (+ x (* y w))) c))

;; ============================================================
;; 4. EDGE DETECTION (Laplaciano 3x3) — recursión sobre filas/columnas
;; ============================================================
(define (edge-recursive bytes-buf w h)
  (define src (bytes->pixel-vector bytes-buf))
  (define out (make-bytes (bytes-length bytes-buf) 0))

  ;; Copia alpha de todos los píxeles tal cual
  (for ([i (in-range (* w h))])
    (bytes-set! out (* i 4) (list-ref (vector-ref src i) 0)))

  ;; Procesa filas 1..h-2 y columnas 1..w-2 de forma recursiva
  (define (process-rows y)
    (when (< y (- h 1))
      (process-cols 1 y)
      (process-rows (+ y 1))))

  (define (process-cols x y)
    (when (< x (- w 1))
      (define base (* 4 (+ x (* y w))))
      ;; Para cada canal de color (R=1, G=2, B=3)
      (for ([c (in-range 1 4)])
        (define val
          (+ (*  8 (vec-channel src x y w c))
             (* -1 (vec-channel src (- x 1) (- y 1) w c))
             (* -1 (vec-channel src x       (- y 1) w c))
             (* -1 (vec-channel src (+ x 1) (- y 1) w c))
             (* -1 (vec-channel src (- x 1) y       w c))
             (* -1 (vec-channel src (+ x 1) y       w c))
             (* -1 (vec-channel src (- x 1) (+ y 1) w c))
             (* -1 (vec-channel src x       (+ y 1) w c))
             (* -1 (vec-channel src (+ x 1) (+ y 1) w c))))
        (bytes-set! out (+ base c) (clamp val)))
      (process-cols (+ x 1) y)))

  (process-rows 1)
  out)

;; ============================================================
;; 5. GAUSSIAN BLUR (Kernel 3x3) — recursión sobre filas/columnas
;; ============================================================
(define (gaussian-recursive bytes-buf w h)
  (define src (bytes->pixel-vector bytes-buf))
  (define out (bytes-copy bytes-buf)) ; Copia bordes sin modificar

  (define (process-rows y)
    (when (< y (- h 1))
      (process-cols 1 y)
      (process-rows (+ y 1))))

  (define (process-cols x y)
    (when (< x (- w 1))
      (define base (* 4 (+ x (* y w))))
      (for ([c (in-range 1 4)])
        (define val
          (+ (* 4 (vec-channel src x       y       w c))
             (* 2 (vec-channel src x       (- y 1) w c))
             (* 2 (vec-channel src x       (+ y 1) w c))
             (* 2 (vec-channel src (- x 1) y       w c))
             (* 2 (vec-channel src (+ x 1) y       w c))
             (* 1 (vec-channel src (- x 1) (- y 1) w c))
             (* 1 (vec-channel src (+ x 1) (- y 1) w c))
             (* 1 (vec-channel src (- x 1) (+ y 1) w c))
             (* 1 (vec-channel src (+ x 1) (+ y 1) w c))))
        (bytes-set! out (+ base c) (quotient val 16)))
      (process-cols (+ x 1) y)))

  (process-rows 1)
  out)
